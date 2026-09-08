#include <string.h>
#include <stdio.h>
#include "list_detail.h"
#include "card.h"
#include "icons.h"
#include "text.h"
#include "cJSON.h"

#define LEFT 12
#define PAD 14
#define WIDTH 456
#define TITLE_MAX_LINES 2
#define BACK_HEIGHT 46
#define ROW_MIN_HEIGHT 54
#define ROW_GAP 6
#define CHECK_SIZE 22

typedef struct {
    int viewport_top;
    int viewport_height;
    int count;
    int top[LIST_DETAIL_MAX_ITEMS + 1];
    int height[LIST_DETAIL_MAX_ITEMS + 1];
    int content_height;
} list_plan;

static const char *string_of(const cJSON *object, const char *key) {
    const cJSON *value = cJSON_GetObjectItemCaseSensitive(object, key);
    return cJSON_IsString(value) ? value->valuestring : NULL;
}

static int title_lines(const cJSON *root, text_line *lines) {
    const char *title = string_of(root, "title");
    if (!title) title = "Liste";
    return text_wrap(&text_font_title, title, strlen(title), WIDTH - 2 * PAD,
                     TITLE_MAX_LINES, lines);
}

static void plan_for(const cJSON *root, int top, int bottom, list_plan *plan) {
    memset(plan, 0, sizeof(*plan));
    text_line title[TITLE_MAX_LINES];
    int titles = title_lines(root, title);
    plan->viewport_top = top + PAD + titles * text_font_title.line_height + 14;
    plan->viewport_height = bottom - PAD - plan->viewport_top;
    if (plan->viewport_height < 1) plan->viewport_height = 1;
    plan->top[0] = 0;
    plan->height[0] = BACK_HEIGHT;
    int cursor = BACK_HEIGHT + ROW_GAP;
    const cJSON *items = cJSON_GetObjectItemCaseSensitive(root, "items");
    const cJSON *item;
    cJSON_ArrayForEach(item, items) {
        if (plan->count >= LIST_DETAIL_MAX_ITEMS) break;
        const char *content = string_of(item, "content");
        text_line lines[2];
        int wrapped = content ? text_wrap(&text_font_body, content, strlen(content),
                                           WIDTH - 2 * PAD - CHECK_SIZE - 14, 2, lines) : 0;
        int height = wrapped * text_font_body.line_height + 16;
        if (height < ROW_MIN_HEIGHT) height = ROW_MIN_HEIGHT;
        plan->count++;
        plan->top[plan->count] = cursor;
        plan->height[plan->count] = height;
        cursor += height + ROW_GAP;
    }
    plan->content_height = cursor > 0 ? cursor - ROW_GAP : 0;
}

static void checkbox(unsigned char *canvas, int x, int y, bool checked) {
    icon_outline(canvas, x, y, CHECK_SIZE, CHECK_SIZE, 2);
    if (!checked) return;
    /* A simple X survives both a normal row and the final focus inversion. */
    for (int i = 4; i < CHECK_SIZE - 4; i++) {
        icon_fill(canvas, x + i, y + i, 2, 2, STRIP_SOLID);
        icon_fill(canvas, x + CHECK_SIZE - i - 2, y + i, 2, 2, STRIP_SOLID);
    }
}

int list_detail_draw(unsigned char *canvas, const char *json, int top, int bottom,
                     int scroll, int focus, const bool *done) {
    cJSON *root = cJSON_Parse(json);
    if (!cJSON_IsObject(root)) { cJSON_Delete(root); return 0; }
    list_plan plan;
    plan_for(root, top, bottom, &plan);
    card_stroke_round(canvas, LEFT, top, LEFT + WIDTH - 1, bottom, 8, 2);
    text_line title[TITLE_MAX_LINES];
    int titles = title_lines(root, title);
    int y = top + PAD;
    for (int i = 0; i < titles; i++) {
        text_draw(canvas, &text_font_title, LEFT + PAD, y,
                  title[i].start, title[i].bytes);
        y += text_font_title.line_height;
    }

    int row_y = plan.viewport_top - scroll;
    if (row_y >= plan.viewport_top && row_y + BACK_HEIGHT <= bottom - PAD) {
        static const char back[] = "Zurück";
        text_draw(canvas, &text_font_body, LEFT + PAD, row_y + 11, back, strlen(back));
        if (focus == 0)
            icon_invert(canvas, LEFT + 6, row_y, WIDTH - 12, BACK_HEIGHT);
    }

    const cJSON *items = cJSON_GetObjectItemCaseSensitive(root, "items");
    const cJSON *item;
    int index = 0;
    cJSON_ArrayForEach(item, items) {
        if (index >= plan.count) break;
        int logical = index + 1;
        row_y = plan.viewport_top + plan.top[logical] - scroll;
        int height = plan.height[logical];
        if (row_y >= plan.viewport_top && row_y + height <= bottom - PAD) {
            int box_y = row_y + (height - CHECK_SIZE) / 2;
            checkbox(canvas, LEFT + PAD, box_y, done && done[index]);
            const char *content = string_of(item, "content");
            if (content) {
                text_line lines[2];
                int count = text_wrap(&text_font_body, content, strlen(content),
                                      WIDTH - 2 * PAD - CHECK_SIZE - 14, 2, lines);
                int text_y = row_y + (height - count * text_font_body.line_height) / 2;
                for (int line = 0; line < count; line++) {
                    text_draw(canvas, &text_font_body, LEFT + PAD + CHECK_SIZE + 14,
                              text_y, lines[line].start, lines[line].bytes);
                    text_y += text_font_body.line_height;
                }
            }
            if (focus == logical)
                icon_invert(canvas, LEFT + 6, row_y, WIDTH - 12, height);
        }
        index++;
    }
    cJSON_Delete(root);
    return plan.count;
}

int list_detail_scroll_for(const char *json, int top, int bottom,
                           int focus, int current_scroll) {
    cJSON *root = cJSON_Parse(json);
    if (!cJSON_IsObject(root)) { cJSON_Delete(root); return current_scroll; }
    list_plan plan;
    plan_for(root, top, bottom, &plan);
    cJSON_Delete(root);
    if (focus < 0) focus = 0;
    if (focus > plan.count) focus = plan.count;
    int row_top = plan.top[focus], row_bottom = row_top + plan.height[focus];
    int scroll = current_scroll;
    if (row_top < scroll) scroll = row_top;
    if (row_bottom > scroll + plan.viewport_height)
        scroll = row_bottom - plan.viewport_height;
    int limit = plan.content_height - plan.viewport_height;
    if (limit < 0) limit = 0;
    if (scroll > limit) scroll = limit;
    if (scroll < 0) scroll = 0;
    return scroll;
}

int list_detail_items(const char *json, char ids[][LIST_DETAIL_ID_CHARS],
                      int capacity) {
    cJSON *root = cJSON_Parse(json);
    if (!cJSON_IsObject(root) || capacity <= 0) { cJSON_Delete(root); return 0; }
    const cJSON *items = cJSON_GetObjectItemCaseSensitive(root, "items");
    const cJSON *item;
    int count = 0;
    cJSON_ArrayForEach(item, items) {
        if (count >= capacity) break;
        const char *id = string_of(item, "id");
        if (!id || strlen(id) != LIST_DETAIL_ID_CHARS - 1) continue;
        snprintf(ids[count], LIST_DETAIL_ID_CHARS, "%s", id);
        count++;
    }
    cJSON_Delete(root);
    return count;
}
