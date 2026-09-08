#pragma once
#include <stdbool.h>
#include <stddef.h>

#define LIST_DETAIL_MAX_ITEMS 20
#define LIST_DETAIL_ID_CHARS 37

/* Draw one interactive list detail. Focus 0 is the back row; 1..count are
 * list items. `done` is device-local desired state and deliberately separate
 * from the server JSON, which contains active items only. */
int list_detail_draw(unsigned char *canvas, const char *json, int top, int bottom,
                     int scroll, int focus, const bool *done);
int list_detail_scroll_for(const char *json, int top, int bottom,
                           int focus, int current_scroll);
int list_detail_items(const char *json, char ids[][LIST_DETAIL_ID_CHARS],
                      int capacity);

