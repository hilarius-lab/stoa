#pragma once

#include <stdbool.h>
#include "driver/i2c_master.h"

/*
 * Read-only battery telemetry for the power controller at 0x34. Waveshare's
 * schematic and board examples name AXP2101; current product prose names TG28.
 * The physical board answers the documented AXP2101 status, VBAT ADC and
 * E-Gauge subset coherently. No PMIC register is ever written, and software
 * does not claim to distinguish an unreadable package marking.
 */
bool battery_start(i2c_master_bus_handle_t bus);

/* Prints the latest cached sample; it never touches I2C from the USB loop. */
void battery_report(void);
