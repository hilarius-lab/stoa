#ifndef EPAPER_DRIVER_H
#define EPAPER_DRIVER_H

#include <stdint.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
typedef uint8_t UBYTE;
typedef uint16_t UWORD;
typedef uint32_t UDOUBLE;


/**
 * GPIO config
**/
#define EPD_SCLK_PIN    11
#define EPD_MOSI_PIN    12

#define EPD_CS_PIN      10

#define EPD_DC_PIN      9

#define EPD_RST_PIN     46
#define EPD_BUSY_PIN    3



#define epaper_rst_1    gpio_set_level(EPD_RST_PIN,1)
#define epaper_rst_0    gpio_set_level(EPD_RST_PIN,0)
#define epaper_cs_1     gpio_set_level(EPD_CS_PIN,1)
#define epaper_cs_0     gpio_set_level(EPD_CS_PIN,0)
#define epaper_dc_1     gpio_set_level(EPD_DC_PIN,1)
#define epaper_dc_0     gpio_set_level(EPD_DC_PIN,0)

#define ReadBusy        gpio_get_level(EPD_BUSY_PIN)




// Display resolution
#define EPD_WIDTH               800
#define EPD_HEIGHT              480
#define EPD_SIZE_MONO           48000
#define EPD_SIZE_4GRAY          96000

// Refresh mode
#define Partial_refresh         0
#define Global_refresh          1

#ifdef __cplusplus
extern "C" {
#endif

void epaper_port_init(void);

void EPD_Init(void);
void EPD_Init_Fast(void);
void EPD_Init_Partial(void);
void EPD_Init_4GRAY(void);
void EPD_Clear(void);
void EPD_Clear_Black(void);
void EPD_Display(const UBYTE *Image);
void EPD_Display_Base(const UBYTE *Image);
void EPD_Display_Fast(const UBYTE *Image);
void EPD_Display_Fast_Base(const UBYTE *Image);
void EPD_Display_OneShot(const UBYTE *Image);
void EPD_Display_Partial(const UBYTE *Image, UWORD Xstart, UWORD Ystart, UWORD Xend, UWORD Yend);
void EPD_Display_Partial_Frame(const UBYTE *Image);
/* Windowed partial update. Transfers only the given rectangle of `Image` and
 * drives only that area with the partial waveform. Unlike the vendor
 * `EPD_Display_Partial` it performs no `EPD_Reset()`, so the controller keeps
 * its initialized state and the 0x26 base RAM the partial waveform compares
 * against; losing those is what displaced text in the vendor path.
 *
 * `byte_x` and `byte_w` are byte columns of 8 pixels, `y` and `h` framebuffer
 * rows. X is addressed in pixels, Y is mirrored against EPD_HEIGHT-1 while the
 * row data stays in normal order — both verified on hardware 2026-09-05; see
 * the comment on the implementation. */
void EPD_Display_Partial_Window(const UBYTE *Image, UWORD byte_x, UWORD y,
                                UWORD byte_w, UWORD h);
void EPD_Display_4Gray(const UBYTE *Image);
void EPD_Sleep(void);

#ifdef __cplusplus
}
#endif



#endif // !EPAPER_PORT_H

