Display transport and controller initialization from Waveshare:
https://github.com/waveshareteam/ESP32-S3-ePaper-3.97
Commit 9b12d40731a80213b927ee8a421cae4082952819, ESP-IDF/01_E-Paper_Example.
Adaptations: remove unused GUI/image headers; bound BUSY polling to 15 seconds.
Partial-frame path added: retain initialized controller state, use the same
full-frame window/cursor/data-entry mode as EPD_Init and waveform 0xFF. The
original cropped-window routine is retained for reference but no longer called
by the UI, after observed displacement of partial text/counter updates.
No PMU/charging register changes.
