#include <stdio.h>
#include <stdbool.h>
#include <string.h>
#include "driver/spi_master.h"
#include "driver/gpio.h"
#include "esp_log.h"

#include "epaper_port.h"


static spi_device_handle_t spi;
static const char *TAG = "EPD_DRIVER";


static void epaper_gpio_Init(void)
{
  gpio_config_t gpio_conf = {};
  gpio_conf.intr_type = GPIO_INTR_DISABLE;
  gpio_conf.mode = GPIO_MODE_OUTPUT;
  gpio_conf.pin_bit_mask = ((uint64_t)0x01<<EPD_RST_PIN) | ((uint64_t)0x01<<EPD_DC_PIN) | ((uint64_t)0x01<<EPD_CS_PIN);
  gpio_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
  gpio_conf.pull_up_en = GPIO_PULLUP_ENABLE;
  ESP_ERROR_CHECK_WITHOUT_ABORT(gpio_config(&gpio_conf));


  gpio_conf.intr_type = GPIO_INTR_DISABLE;
  gpio_conf.mode = GPIO_MODE_INPUT;
  gpio_conf.pin_bit_mask = ((uint64_t)0x01<<EPD_BUSY_PIN);
  gpio_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
  gpio_conf.pull_up_en = GPIO_PULLDOWN_ENABLE;
  ESP_ERROR_CHECK_WITHOUT_ABORT(gpio_config(&gpio_conf));

  epaper_rst_1;
}

void epaper_port_init(void)
{
    esp_err_t ret;
    spi_bus_config_t buscfg = 
    {
        .miso_io_num = -1,
        .mosi_io_num = EPD_MOSI_PIN,
        .sclk_io_num = EPD_SCLK_PIN,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = 65536,  
    };
    spi_device_interface_config_t devcfg = 
    {
        .spics_io_num = -1,
        .clock_speed_hz = 20 * 1000 * 1000, 
        .mode = 0,
        .queue_size = 1, 
    };
    
    ret = spi_bus_initialize(SPI3_HOST, &buscfg, SPI_DMA_CH_AUTO);
    ESP_ERROR_CHECK(ret);
    ret = spi_bus_add_device(SPI3_HOST, &devcfg, &spi);
    ESP_ERROR_CHECK(ret);

    epaper_gpio_Init();
}

esp_err_t spi_send_data(uint8_t *data, size_t data_size) {
    esp_err_t ret;
    spi_transaction_t t;
    memset(&t, 0, sizeof(t));

    const size_t chunk_size = 1024;
    for (size_t i = 0; i < data_size; i += chunk_size) {
        size_t chunk_len = (i + chunk_size > data_size) ? (data_size - i) : chunk_size;
        t.length = chunk_len * 8;
        t.tx_buffer = data + i; 

        ret = spi_device_polling_transmit(spi, &t);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "SPI transmission failed: %s", esp_err_to_name(ret));
            return ret;
        }
    }
    return ESP_OK;
}

static void spi_send_byte(uint8_t cmd)
{
    esp_err_t ret;
    spi_transaction_t t; 
    memset(&t, 0, sizeof(t)); 
    
    t.length = 8;      
    t.tx_buffer = &cmd;
    t.rx_buffer = NULL;  
    t.rxlength = 0; 
    
    ret = spi_device_polling_transmit(spi, &t);
    assert(ret == ESP_OK);
}

/******************************************************************************
function :	Software reset
parameter:
******************************************************************************/
static void EPD_Reset(void)
{
    epaper_rst_1;
    vTaskDelay(pdMS_TO_TICKS(50));
    epaper_rst_0;
    vTaskDelay(pdMS_TO_TICKS(2));
    epaper_rst_1;
    vTaskDelay(pdMS_TO_TICKS(50));
}

/******************************************************************************
function :	send command
parameter:
     Reg : Command register
******************************************************************************/
static void EPD_SendCommand(UBYTE Reg)
{
    epaper_dc_0;
    spi_send_byte(Reg);
}

/******************************************************************************
function :	send data
parameter:
    Data : Write data
******************************************************************************/
static void EPD_SendData(UBYTE Data)
{
    epaper_dc_1;
    spi_send_byte(Data);
}

static void EPD_SendDataBuffer(const UBYTE* buffer, UDOUBLE length)
{
    epaper_dc_1; 
    
    esp_err_t ret;
    const size_t chunk_size = 4096;
    
    for (size_t i = 0; i < length; i += chunk_size) {
        size_t current_chunk = (i + chunk_size > length) ? (length - i) : chunk_size;
        
        spi_transaction_t t;
        memset(&t, 0, sizeof(t));
        
        t.length = current_chunk * 8;
        t.tx_buffer = buffer + i;
        
        ret = spi_device_polling_transmit(spi, &t);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "SPI transmission failed: %s", esp_err_to_name(ret));
            return;
        }
    }
    
    ESP_LOGD(TAG, "All %lu bytes transmitted successfully", (unsigned long)length);
}

/******************************************************************************
function :	Wait until the busy_pin goes LOW
parameter:
******************************************************************************/
static void EPD_ReadBusy(void)
{
    // ESP_LOGI(TAG,"e-Paper busy");
    vTaskDelay(pdMS_TO_TICKS(100));
    for (unsigned wait = 0; wait < 750; ++wait)
    {
        if(!ReadBusy){break;}
        // getstat();
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    // ESP_LOGI(TAG,"e-Paper busy release");
}

/******************************************************************************
function :	Power on/off control for e-ink screens
parameter:
******************************************************************************/

/******************************************************************************
function :	Turn On Display full
parameter:
******************************************************************************/
static void EPD_TurnOnDisplay(void)
{
    EPD_SendCommand(0x22);
    EPD_SendData(0xF7);
	EPD_SendCommand(0x20);
    EPD_ReadBusy();
}

static void EPD_TurnOnDisplay_Fast(void)
{
    EPD_SendCommand(0x22);
    EPD_SendData(0xD7);
	EPD_SendCommand(0x20);
    EPD_ReadBusy();
}

static void EPD_TurnOnDisplay_4GRAY(void)
{
    EPD_SendCommand(0x22);
    EPD_SendData(0xD7);
	EPD_SendCommand(0x20);
    EPD_ReadBusy();
}

static void EPD_TurnOnDisplay_Part(void)
{
    EPD_SendCommand(0x22);
    EPD_SendData(0xFF);
    EPD_SendCommand(0x20);
    EPD_ReadBusy();
}

/******************************************************************************
function :	Initialize the e-Paper register
parameter:
******************************************************************************/
void EPD_Init(void)
{
    vTaskDelay(pdMS_TO_TICKS(10));
    EPD_Reset();

    EPD_ReadBusy();
    EPD_SendCommand(0x12);  //SWRESET
    EPD_ReadBusy();

    EPD_SendCommand(0x18);
    EPD_SendData(0x80);

    EPD_SendCommand(0x0C);
	EPD_SendData(0xAE);
	EPD_SendData(0xC7);
	EPD_SendData(0xC3);
	EPD_SendData(0xC0);
	EPD_SendData(0x80);

    EPD_SendCommand(0x01); //Driver output control
    EPD_SendData((EPD_HEIGHT-1)%256);
    EPD_SendData((EPD_HEIGHT-1)/256);
    EPD_SendData(0x02);

    EPD_SendCommand(0x3C); //BorderWavefrom
    EPD_SendData(0x01);

    EPD_SendCommand(0x11); //data entry mode       
	EPD_SendData(0x01);

	EPD_SendCommand(0x44); //set Ram-X address start/end position   
	EPD_SendData(0x00);
	EPD_SendData(0x00);
	EPD_SendData((EPD_WIDTH-1)%256);    
	EPD_SendData((EPD_WIDTH-1)/256);

	EPD_SendCommand(0x45); //set Ram-Y address start/end position    
    EPD_SendData((EPD_HEIGHT-1)%256);    
	EPD_SendData((EPD_HEIGHT-1)/256);  
	EPD_SendData(0x00);
	EPD_SendData(0x00);

    EPD_SendCommand(0x4E);   // set RAM x address count to 0;
	EPD_SendData(0x00);
	EPD_SendData(0x00);
	EPD_SendCommand(0x4F);   // set RAM y address count to 0X199;    
	EPD_SendData(0x00);
	EPD_SendData(0x00);
    EPD_ReadBusy();

}
//Fast update initialization
void EPD_Init_Fast(void)
{
    vTaskDelay(pdMS_TO_TICKS(500));
	EPD_Reset(); 
	
	EPD_ReadBusy();   
	EPD_SendCommand(0x12);  //SWRESET
	EPD_ReadBusy();   
	
	EPD_SendCommand(0x0C);
	EPD_SendData(0xAE);
	EPD_SendData(0xC7);
	EPD_SendData(0xC3);
	EPD_SendData(0xC0);
	EPD_SendData(0x80);
	
	EPD_SendCommand(0x01); //Driver output control      
	EPD_SendData((EPD_HEIGHT-1)%256);   
	EPD_SendData((EPD_HEIGHT-1)/256);
	EPD_SendData(0x02);

	EPD_SendCommand(0x11); //data entry mode       
	EPD_SendData(0x01);

	EPD_SendCommand(0x44); //set Ram-X address start/end position   
	EPD_SendData(0x00);
	EPD_SendData(0x00);
	EPD_SendData((EPD_WIDTH-1)%256);    
	EPD_SendData((EPD_WIDTH-1)/256);

	EPD_SendCommand(0x45); //set Ram-Y address start/end position    
    EPD_SendData((EPD_HEIGHT-1)%256);    
	EPD_SendData((EPD_HEIGHT-1)/256);  
	EPD_SendData(0x00);
	EPD_SendData(0x00);


	EPD_SendCommand(0x4E);   // set RAM x address count to 0;
	EPD_SendData(0x00);
	EPD_SendData(0x00);
	EPD_SendCommand(0x4F);   // set RAM y address count to 0X199;    
	EPD_SendData(0x00);
	EPD_SendData(0x00);
    EPD_ReadBusy();

	EPD_SendCommand(0x3C); //BorderWavefrom
	EPD_SendData(0x01);	
	
	EPD_SendCommand(0x18);   
	EPD_SendData(0x80); 
	//Fast(1.5s)
	EPD_SendCommand(0x1A); 
	EPD_SendData(0x6A);

}
//4 Gray update initialization
void EPD_Init_4GRAY(void)
{
    vTaskDelay(pdMS_TO_TICKS(500));
	EPD_Reset();
	
	EPD_ReadBusy();   
	EPD_SendCommand(0x12);  //SWRESET
	EPD_ReadBusy();   
	
	EPD_SendCommand(0x0C);
	EPD_SendData(0xAE);
	EPD_SendData(0xC7);
	EPD_SendData(0xC3);
	EPD_SendData(0xC0);
	EPD_SendData(0x80);
	
	EPD_SendCommand(0x01); //Driver output control      
	EPD_SendData((EPD_HEIGHT-1)%256);   
	EPD_SendData((EPD_HEIGHT-1)/256);
	EPD_SendData(0x02);

	EPD_SendCommand(0x11); //data entry mode       
	EPD_SendData(0x01);

	EPD_SendCommand(0x44); //set Ram-X address start/end position   
	EPD_SendData(0x00);
	EPD_SendData(0x00);
	EPD_SendData((EPD_WIDTH-1)%256);    
	EPD_SendData((EPD_WIDTH-1)/256);

	EPD_SendCommand(0x45); //set Ram-Y address start/end position    
    EPD_SendData((EPD_HEIGHT-1)%256);    
	EPD_SendData((EPD_HEIGHT-1)/256);  
	EPD_SendData(0x00);
	EPD_SendData(0x00);


	EPD_SendCommand(0x4E);   // set RAM x address count to 0;
	EPD_SendData(0x00);
	EPD_SendData(0x00);
	EPD_SendCommand(0x4F);   // set RAM y address count to 0X199;    
	EPD_SendData(0x00);
	EPD_SendData(0x00);
    EPD_ReadBusy();

	EPD_SendCommand(0x3C); //BorderWavefrom
	EPD_SendData(0x01);	
	
	EPD_SendCommand(0x18);   
	EPD_SendData(0x80); 
	//4 Gray
	EPD_SendCommand(0x1A); 
	EPD_SendData(0x5A);

}
/******************************************************************************
function :	Clear screen
parameter:
******************************************************************************/
void EPD_Clear(void)
{
    UWORD Width, Height;
    Width = (EPD_WIDTH % 8 == 0)? (EPD_WIDTH / 8 ): (EPD_WIDTH / 8 + 1);
    Height = EPD_HEIGHT;
    
    EPD_SendCommand(0x24);
    for (UWORD j = 0; j < Height; j++) {
        for (UWORD i = 0; i < Width; i++) {
            EPD_SendData(0XFF);
        }
        vTaskDelay(pdMS_TO_TICKS(1));
    }
    
    EPD_SendCommand(0x26);
    for (UWORD j = 0; j < Height; j++) {
        for (UWORD i = 0; i < Width; i++) {
            EPD_SendData(0XFF);
        }
        vTaskDelay(pdMS_TO_TICKS(1));
    }
    
    EPD_TurnOnDisplay();
}

void EPD_Clear_Black(void)
{
    UWORD Width, Height;
    Width = (EPD_WIDTH % 8 == 0)? (EPD_WIDTH / 8 ): (EPD_WIDTH / 8 + 1);
    Height = EPD_HEIGHT;

    EPD_SendCommand(0x24);
    for (UWORD j = 0; j < Height; j++) {
        for (UWORD i = 0; i < Width; i++) {
            EPD_SendData(0X00);
        }
    }
    EPD_SendCommand(0x26);
    for (UWORD j = 0; j < Height; j++) {
        for (UWORD i = 0; i < Width; i++) {
            EPD_SendData(0X00);
        }
    }
    EPD_TurnOnDisplay();
}


/******************************************************************************
function :	Sends the image buffer in RAM to e-Paper and displays
parameter:
******************************************************************************/
void EPD_Display(const UBYTE *Image)
{
    UWORD Width, Height;
    Width = (EPD_WIDTH % 8 == 0)? (EPD_WIDTH / 8 ): (EPD_WIDTH / 8 + 1);
    Height = EPD_HEIGHT;
    UDOUBLE buffer_size = Width * Height;
    
    EPD_SendCommand(0x24);
    EPD_SendDataBuffer(Image, buffer_size);
    
    EPD_TurnOnDisplay();
}

void EPD_Display_Base(const UBYTE *Image)
{
    UWORD Width, Height;
    Width = (EPD_WIDTH % 8 == 0)? (EPD_WIDTH / 8 ): (EPD_WIDTH / 8 + 1);
    Height = EPD_HEIGHT;
    UDOUBLE buffer_size = Width * Height;
    
    EPD_SendCommand(0x24);
    EPD_SendDataBuffer(Image, buffer_size);

    
    
    EPD_SendCommand(0x26);
    EPD_SendDataBuffer(Image, buffer_size);
    
    EPD_TurnOnDisplay();
}

void EPD_Display_Fast(const UBYTE *Image)
{
    UWORD Width, Height;
    Width = (EPD_WIDTH % 8 == 0)? (EPD_WIDTH / 8 ): (EPD_WIDTH / 8 + 1);
    Height = EPD_HEIGHT;
    UDOUBLE buffer_size = Width * Height;
    
    EPD_SendCommand(0x24);
    EPD_SendDataBuffer(Image, buffer_size);
    
    EPD_TurnOnDisplay_Fast();
}

void EPD_Display_Fast_Base(const UBYTE *Image)
{
    UWORD Width, Height;
    Width = (EPD_WIDTH % 8 == 0)? (EPD_WIDTH / 8 ): (EPD_WIDTH / 8 + 1);
    Height = EPD_HEIGHT;
    UDOUBLE buffer_size = Width * Height;
    
    EPD_SendCommand(0x24);
    EPD_SendDataBuffer(Image, buffer_size);
    
    EPD_SendCommand(0x26);
    EPD_SendDataBuffer(Image, buffer_size);

    EPD_TurnOnDisplay_Fast();
}

void EPD_Display_OneShot(const UBYTE *Image)
{
    UWORD Width, Height;
    Width = (EPD_WIDTH % 8 == 0)? (EPD_WIDTH / 8 ): (EPD_WIDTH / 8 + 1);
    Height = EPD_HEIGHT;
    UDOUBLE buffer_size = Width * Height;
    
    EPD_SendCommand(0x24);
    
    epaper_dc_1;
    esp_err_t ret;
    spi_transaction_t t;
    memset(&t, 0, sizeof(t));
    
    t.length = buffer_size * 8;
    t.tx_buffer = Image;
    t.rx_buffer = NULL;  
    t.rxlength = 0;  
    
    ESP_LOGI(TAG, "Starting one-shot transmission of %lu bytes", (unsigned long)buffer_size);
    ret = spi_device_polling_transmit(spi, &t);
    
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "One-shot SPI transmission failed: %s", esp_err_to_name(ret));
        return;
    }
    
    ESP_LOGI(TAG, "One-shot transmission completed");
    EPD_TurnOnDisplay();
}

/******************************************************************************
function :	Sends the image buffer in RAM to e-Paper and displays
parameter:
******************************************************************************/
void EPD_Display_Partial_Frame(const UBYTE *Image)
{
    // Use exactly the proven full-frame addressing from EPD_Init. The vendor's
    // cropped path resets the controller and uses a different window/cursor;
    // mixing it with our full-frame canvas visibly displaced text and digits.
    // Transfer the complete bitmap, but drive the panel with the partial waveform.
    // No hardware/SW reset: keep the controller's initialized state and base RAM.
    EPD_SendCommand(0x18); EPD_SendData(0x80);
    EPD_SendCommand(0x3C); EPD_SendData(0x80);
    EPD_SendCommand(0x11); EPD_SendData(0x01);
    EPD_SendCommand(0x44);
    EPD_SendData(0); EPD_SendData(0);
    EPD_SendData((EPD_WIDTH-1)&0xff); EPD_SendData((EPD_WIDTH-1)>>8);
    EPD_SendCommand(0x45);
    EPD_SendData((EPD_HEIGHT-1)&0xff); EPD_SendData((EPD_HEIGHT-1)>>8);
    EPD_SendData(0); EPD_SendData(0);
    EPD_SendCommand(0x4E); EPD_SendData(0); EPD_SendData(0);
    EPD_SendCommand(0x4F); EPD_SendData(0); EPD_SendData(0);
    EPD_SendCommand(0x24);
    EPD_SendDataBuffer(Image,((EPD_WIDTH+7)/8)*EPD_HEIGHT);
    EPD_TurnOnDisplay_Part();
}

/******************************************************************************
function :  Windowed partial update.
parameter:  byte_x/byte_w are byte columns of 8 pixels, y/h are framebuffer rows.

The command sequence is deliberately identical to EPD_Display_Partial_Frame
above; only the window registers are narrowed and only the rectangle's bytes
are transferred. Above all there is no EPD_Reset(): a reset would drop the
controller's initialization and the 0x26 base RAM that the partial waveform
uses as its comparison reference, which is exactly why the vendor's cropped
path displaced text. 0x26 is not written here either, so the base established
by the last EPD_Display_Base stays the reference.

RAM-Y runs opposite to the framebuffer. Verified on hardware 2026-09-05: a
window addressed with the framebuffer's own row numbers lands mirrored about
the horizontal centre line, so the window is addressed as EPD_HEIGHT-1-row.
The row data itself is sent in normal order; mirroring the rows as well flips
the content inside the rectangle. Both halves of that were measured against
edge-aligned probes and against the status bar the UI draws, which the window
covers exactly.
******************************************************************************/
void EPD_Display_Partial_Window(const UBYTE *Image, UWORD byte_x, UWORD y,
                                UWORD byte_w, UWORD h)
{
    const UWORD line_bytes = (EPD_WIDTH + 7) / 8;
    if (!Image || !byte_w || !h) return;
    if (byte_x + byte_w > line_bytes || y + h > EPD_HEIGHT) return;

    const UWORD x_start = byte_x * 8;
    const UWORD x_end = (UWORD)((byte_x + byte_w) * 8 - 1);
    const UWORD y_start = y;
    const UWORD y_end = (UWORD)(y + h - 1);

    const UWORD window_hi = (UWORD)(EPD_HEIGHT - 1 - y_start);
    const UWORD window_lo = (UWORD)(EPD_HEIGHT - 1 - y_end);

    EPD_SendCommand(0x18); EPD_SendData(0x80);
    EPD_SendCommand(0x3C); EPD_SendData(0x80);
    EPD_SendCommand(0x11); EPD_SendData(0x01);
    EPD_SendCommand(0x44);
    EPD_SendData(x_start & 0xff); EPD_SendData(x_start >> 8);
    EPD_SendData(x_end & 0xff);   EPD_SendData(x_end >> 8);
    /* High end first, matching the working full-frame path. */
    EPD_SendCommand(0x45);
    EPD_SendData(window_hi & 0xff); EPD_SendData(window_hi >> 8);
    EPD_SendData(window_lo & 0xff); EPD_SendData(window_lo >> 8);
    EPD_SendCommand(0x4E);
    EPD_SendData(x_start & 0xff); EPD_SendData(x_start >> 8);
    EPD_SendCommand(0x4F);
    EPD_SendData(window_lo & 0xff); EPD_SendData(window_lo >> 8);

    EPD_SendCommand(0x24);
    for (UWORD row = 0; row < h; row++)
        EPD_SendDataBuffer(Image + (UDOUBLE)(y + row) * line_bytes + byte_x, byte_w);

    EPD_TurnOnDisplay_Part();
}

void EPD_Display_Partial(const UBYTE *Image, UWORD Xstart, UWORD Ystart, UWORD Xend, UWORD Yend)
{
    if((Xstart % 8 + Xend % 8 == 8 && Xstart % 8 > Xend % 8) || Xstart % 8 + Xend % 8 == 0 || (Xend - Xstart)%8 == 0)
    {
        Xstart = Xstart / 8 ;
        Xend = Xend / 8;
    }
    else
    {
        Xstart = Xstart / 8 ;
        Xend = Xend % 8 == 0 ? Xend / 8 : Xend / 8 + 1;
    }

    UWORD Width = Xend - Xstart;
    UDOUBLE IMAGE_COUNTER = Width * (Yend - Ystart);

    Xend -= 1;
    Yend -= 1;	

    EPD_Reset();

    EPD_SendCommand(0x18);
    EPD_SendData(0x80);

    EPD_SendCommand(0x3C);
    EPD_SendData(0x80);

    EPD_SendCommand(0x44);
    EPD_SendData((Xstart*8) & 0xFF);
    EPD_SendData(((Xstart*8) >> 8) & 0xFF);
    EPD_SendData((Xend*8) & 0xFF);
    EPD_SendData(((Xend*8) >> 8) & 0xFF);

    EPD_SendCommand(0x45);
    EPD_SendData(Yend & 0xFF);
    EPD_SendData((Yend >> 8) & 0xFF);
    EPD_SendData(Ystart & 0xFF);
    EPD_SendData((Ystart >> 8) & 0xFF);

    EPD_SendCommand(0x4E); 
    EPD_SendData((Xstart*8) & 0xFF);
    EPD_SendData(((Xstart*8) >> 8) & 0xFF);

    EPD_SendCommand(0x4F);
    EPD_SendData(Ystart & 0xFF);
    EPD_SendData((Ystart >> 8) & 0xFF);

    EPD_SendCommand(0x24);   //Write Black and White image to RAM

    EPD_SendDataBuffer(Image, IMAGE_COUNTER);

    EPD_TurnOnDisplay_Part();
}

void EPD_Display_4Gray(const UBYTE *Image)
{
    UDOUBLE i,j,k;
    UBYTE temp1,temp2,temp3;
    UWORD Width, Height;
    Width = (EPD_WIDTH % 8 == 0)? (EPD_WIDTH / 8 ): (EPD_WIDTH / 8 + 1);
    Height = EPD_HEIGHT;
    UDOUBLE IMAGE_COUNTER = Width * Height;
    // old  data
    EPD_SendCommand(0x24);
    for(i=0; i<IMAGE_COUNTER; i++) { 
        temp3=0;
        for(j=0; j<2; j++) {
            temp1 = Image[i*2+j];
            for(k=0; k<2; k++) {
                temp2 = temp1&0xC0;
                if(temp2 == 0xC0)
                    temp3 |= 0x00;
                else if(temp2 == 0x00)
                    temp3 |= 0x01; 
                else if(temp2 == 0x80)
                    temp3 |= 0x01; 
                else //0x40
                    temp3 |= 0x00; 
                temp3 <<= 1;

                temp1 <<= 2;
                temp2 = temp1&0xC0 ;
                if(temp2 == 0xC0) 
                    temp3 |= 0x00;
                else if(temp2 == 0x00) 
                    temp3 |= 0x01;
                else if(temp2 == 0x80)
                    temp3 |= 0x01; 
                else    //0x40
                    temp3 |= 0x00;	
                if(j!=1 || k!=1)
                    temp3 <<= 1;

                temp1 <<= 2;
            }
        }
        EPD_SendData(temp3);
        // printf("%x",temp3);
    }

    EPD_SendCommand(0x26); 
    for(i=0; i<IMAGE_COUNTER; i++) {
        temp3=0;
        for(j=0; j<2; j++) {
            temp1 = Image[i*2+j];
            for(k=0; k<2; k++) {
                temp2 = temp1&0xC0 ;
                if(temp2 == 0xC0)
                    temp3 |= 0x00;//white
                else if(temp2 == 0x00)
                    temp3 |= 0x01;  //black
                else if(temp2 == 0x80)
                    temp3 |= 0x00;  //gray1
                else //0x40
                    temp3 |= 0x01; //gray2
                temp3 <<= 1;

                temp1 <<= 2;
                temp2 = temp1&0xC0 ;
                if(temp2 == 0xC0)  //white
                    temp3 |= 0x00;
                else if(temp2 == 0x00) //black
                    temp3 |= 0x01;
                else if(temp2 == 0x80)
                    temp3 |= 0x00; //gray1
                else    //0x40
                    temp3 |= 0x01;	//gray2
                if(j!=1 || k!=1)
                    temp3 <<= 1;

                temp1 <<= 2;
            }
        }
        EPD_SendData(temp3);
        // printf("%x",temp3);
    }
    EPD_TurnOnDisplay_4GRAY();
}

/******************************************************************************
function :	Enter sleep mode
parameter:
******************************************************************************/
void EPD_Sleep(void)
{
    EPD_SendCommand(0x10); //enter deep sleep
    EPD_SendData(0x01);
    vTaskDelay(pdMS_TO_TICKS(10));
    epaper_rst_0;
    epaper_cs_0;
    epaper_dc_0;
    vTaskDelay(pdMS_TO_TICKS(10));
}

