#include <stdio.h>
#include <stdint.h>
#include <stdatomic.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/i2c_master.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "battery.h"
#include "screen.h"

#define BATTERY_I2C_ADDRESS 0x34
#define BATTERY_SAMPLE_INTERVAL_MS 5000

static i2c_master_dev_handle_t power_device;
static atomic_bool communication_ok, compatible, battery_present;
static atomic_bool external_power, charging, gauge_enabled;
static atomic_uint percentage, voltage_mv, samples;
static atomic_int last_error;
static _Atomic int64_t sampled_at_us;

static esp_err_t read_register(uint8_t address, uint8_t *value, size_t length) {
    return i2c_master_transmit_receive(power_device, &address, 1, value, length,
                                       100);
}

static bool take_sample(void) {
    uint8_t status1 = 0, status2 = 0, control = 0, vbat[2] = {0}, soc = 0;
    esp_err_t err = read_register(0x00, &status1, 1);
    if (err == ESP_OK) err = read_register(0x01, &status2, 1);
    if (err == ESP_OK) err = read_register(0x18, &control, 1);
    /* The datasheet requires the high ADC byte to be read before the low one;
     * one auto-incrementing transaction preserves that order. */
    if (err == ESP_OK) err = read_register(0x34, vbat, sizeof(vbat));
    if (err == ESP_OK) err = read_register(0xA4, &soc, 1);

    atomic_store(&last_error, err);
    atomic_fetch_add(&samples, 1);
    atomic_store(&sampled_at_us, esp_timer_get_time());
    if (err != ESP_OK) {
        atomic_store(&communication_ok, false);
        screen_status_battery(false, 0, false);
        ESP_LOGW("battery", "read failed: %s", esp_err_to_name(err));
        return false;
    }

    unsigned millivolts = ((unsigned)(vbat[0] & 0x3F) << 8) | vbat[1];
    bool family_match = (status1 & 0xC0) == 0 && (status2 & 0x80) == 0 &&
                        (status2 & 0x10) != 0 && (control & 0xF0) == 0;
    bool present = (status1 & 0x08) != 0;
    bool gauge = (control & 0x08) != 0;
    bool plausible = family_match && present && gauge && soc <= 100 &&
                     millivolts >= 2500 && millivolts <= 4600;

    atomic_store(&communication_ok, true);
    atomic_store(&compatible, family_match);
    atomic_store(&battery_present, present);
    atomic_store(&external_power, (status1 & 0x20) != 0);
    atomic_store(&charging, ((status2 >> 5) & 0x03) == 1);
    atomic_store(&gauge_enabled, gauge);
    atomic_store(&percentage, soc);
    atomic_store(&voltage_mv, millivolts);
    screen_status_battery(plausible, soc, plausible && atomic_load(&charging));
    ESP_LOGI("battery",
             "read-only PMIC sample compatible=%d present=%d usb=%d charging=%d gauge=%d soc=%u voltage=%umV",
             family_match, present, (status1 & 0x20) != 0,
             ((status2 >> 5) & 0x03) == 1, gauge, soc, millivolts);
    return plausible;
}

static void battery_task(void *unused) {
    (void)unused;
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(BATTERY_SAMPLE_INTERVAL_MS));
        take_sample();
    }
}

bool battery_start(i2c_master_bus_handle_t bus) {
    if (!bus) return false;
    i2c_device_config_t configuration = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = BATTERY_I2C_ADDRESS,
        .scl_speed_hz = 100000,
    };
    esp_err_t err = i2c_master_bus_add_device(bus, &configuration, &power_device);
    if (err != ESP_OK) {
        atomic_store(&last_error, err);
        ESP_LOGW("battery", "cannot add PMIC at 0x34: %s", esp_err_to_name(err));
        return false;
    }
    take_sample();
    if (xTaskCreate(battery_task, "battery", 3072, NULL, 2, NULL) != pdPASS) {
        ESP_LOGW("battery", "cannot start sampler task");
        return false;
    }
    return true;
}

void battery_report(void) {
    int64_t age_us = esp_timer_get_time() - atomic_load(&sampled_at_us);
    if (age_us < 0) age_us = 0;
    esp_err_t err = (esp_err_t)atomic_load(&last_error);
    printf("BATTERY: interface=axp2101_tg28_compatible address=0x34 communication=%s compatible=%s "
           "battery=%s usb=%s charging=%s gauge=%s percent=%u voltage_mv=%u age_s=%lld samples=%u error=%s\n",
           atomic_load(&communication_ok) ? "ok" : "failed",
           atomic_load(&compatible) ? "yes" : "no",
           atomic_load(&battery_present) ? "present" : "absent",
           atomic_load(&external_power) ? "present" : "absent",
           atomic_load(&charging) ? "yes" : "no",
           atomic_load(&gauge_enabled) ? "enabled" : "disabled",
           atomic_load(&percentage), atomic_load(&voltage_mv),
           (long long)(age_us / 1000000), atomic_load(&samples),
           esp_err_to_name(err));
}
