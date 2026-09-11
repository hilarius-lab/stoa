#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdatomic.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <dirent.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "driver/i2c_master.h"
#include "driver/i2s_std.h"
#include "driver/gpio.h"
#include "esp_codec_dev.h"
#include "esp_codec_dev_defaults.h"
#include "esp_aac_enc.h"
#include "mp4_muxer.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "storage.h"
#include "screen.h"
#include "recorder.h"
#include "driver/usb_serial_jtag.h"
#include "mbedtls/sha256.h"
#include "journal.h"
#include "memo_queue.h"
#include "api_client.h"
#include "diagnostic_log.h"
#include "battery.h"

static atomic_bool held, busy, test_requested, queue_rescan_requested;
static portMUX_TYPE context_lock=portMUX_INITIALIZER_UNLOCKED;
static char clarification_context_id[JOURNAL_UUID_CHARS];
static atomic_bool export_requested;
static char diagnostic_dir[40];
static unsigned diagnostic_segments;
typedef struct { bool list; bool discard; bool explain; bool discard_all; unsigned expected; char id[9]; } file_command;
static QueueHandle_t file_commands;
// Explicit USB file-transfer protocol, never sent to the diagnostic logger.
static bool usb_line(const char *line) {
    size_t n=strlen(line);
    return usb_serial_jtag_write_bytes(line,n,pdMS_TO_TICKS(2000))==n;
}
static void export_memo(const char *directory,unsigned segments) {
    char path[64],line[600]; uint8_t data[256],hash[32];
    for(unsigned s=0;s<segments;s++) {
        snprintf(path,sizeof(path),"%s/%08u.M4A",directory,s);
        FILE *f=fopen(path,"rb"); if(!f) { usb_line("@ERROR missing_segment\n"); return; }
        fseek(f,0,SEEK_END); long size=ftell(f); rewind(f);
        snprintf(line,sizeof(line),"\n@FILE %u %ld\n",s,size);
        if(!usb_line(line)) { fclose(f); return; }
        mbedtls_sha256_context sha; mbedtls_sha256_init(&sha); mbedtls_sha256_starts(&sha,0);
        size_t offset=0,n;
        while((n=fread(data,1,sizeof(data),f))>0) {
            mbedtls_sha256_update(&sha,data,n);
            int prefix=snprintf(line,sizeof(line),"@DATA %u ",(unsigned)offset);
            for(size_t i=0;i<n;i++) snprintf(line+prefix+i*2,3,"%02x",data[i]);
            strcpy(line+prefix+n*2,"\n");
            if(!usb_line(line)) { fclose(f); mbedtls_sha256_free(&sha); return; }
            // Leave headroom for the USB/JTAG hardware FIFO and host scheduling.
            vTaskDelay(pdMS_TO_TICKS(20));
            offset+=n;
        }
        fclose(f); mbedtls_sha256_finish(&sha,hash); mbedtls_sha256_free(&sha);
        strcpy(line,"@END ");
        for(int i=0;i<32;i++) snprintf(line+5+i*2,3,"%02x",hash[i]);
        strcpy(line+69,"\n"); if(!usb_line(line)) return;
    }
    usb_line("@DONE\n");
}
static bool memo_id_valid(const char *id) {
    return id && strlen(id)==8 && strspn(id,"0123456789abcdefABCDEF")==8;
}
static bool memo_info(const char *id,unsigned *segments,unsigned long long *samples) {
    if(!memo_id_valid(id)) return false;
    char path[64]; snprintf(path,sizeof(path),"/sdcard/MEMOS/%s/COMPLETE.TXT",id);
    FILE *f=fopen(path,"rb"); if(!f) return false;
    bool ok=fscanf(f,"local_memo_v1\nsegments=%u\nsamples=%llu",segments,samples)==2;
    fclose(f);
    return ok && *segments>0 && *segments<=32 && *samples>0;
}
/* The listing alone cannot say which session carries a mark, and guessing from
 * segment count or size is exactly the kind of plausible-looking inference that
 * deletes the wrong recording. So `memo-list` reads the journal per session and
 * names the states. A session whose journal cannot be replayed reports `?`
 * rather than zeros — unknown is not the same as clean. */
static void memo_states(const char *id,unsigned *segments,unsigned *ready,unsigned *acked,
                        unsigned *attention,bool *known) {
    *segments=0; *ready=0; *acked=0; *attention=0; *known=false;
    char directory[40];
    snprintf(directory,sizeof(directory),"/sdcard/MEMOS/%s",id);
    journal_session *session=heap_caps_malloc(sizeof(journal_session),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!session) return;
    journal_session_init(session,directory);
    if(journal_replay(session)) {
        *segments=session->chunk_count;
        *ready=journal_count_state(session,CHUNK_READY)+journal_count_state(session,CHUNK_UPLOADING);
        *acked=journal_count_state(session,CHUNK_ACKED);
        *attention=journal_count_state(session,CHUNK_ATTENTION)+(session->create_attention?1:0);
        *known=true;
    }
    free(session);
}

/* Deliberately discard one session: the fourth end state H1 names and the only
 * one the device had no way to reach. A segment could enter `attention` and
 * never leave, which left the warning permanently lit and therefore useless.
 *
 * Refused while anything is still deliverable. `ready` means the recording
 * exists and has not reached the server, and no convenience is worth turning
 * "I want the warning gone" into "the audio is gone". Only a session whose
 * remaining segments are broken or already delivered may go. */
/* Result of one discard attempt, so the bulk path can report per session
 * instead of stopping at the first refusal. */
typedef enum { DISCARD_DONE, DISCARD_DELIVERABLE, DISCARD_UNKNOWN, DISCARD_BROKEN } discard_result;

static discard_result discard_one(const char *id,unsigned *removed_out,unsigned *attention_out) {
    char directory[40];
    snprintf(directory,sizeof(directory),"/sdcard/MEMOS/%s",id);
    journal_session *session=heap_caps_malloc(sizeof(journal_session),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!session) return DISCARD_BROKEN;
    journal_session_init(session,directory);
    bool replayed=journal_replay(session);
    unsigned ready=0,uploading=0,attention=0;
    if(replayed) {
        ready=journal_count_state(session,CHUNK_READY);
        uploading=journal_count_state(session,CHUNK_UPLOADING);
        attention=journal_count_state(session,CHUNK_ATTENTION);
    }
    free(session);
    /* A directory without a replayable journal may still be discarded: it is
     * exactly the stub a broken recording leaves behind, and refusing would make
     * the damaged cases the only ones that cannot be cleaned up. It has no
     * deliverable segments by definition — there is no record of any. */
    if(replayed && (ready||uploading)) return DISCARD_DELIVERABLE;

    /* Everything goes, journal included: this session is meant to stop
     * existing. That is the difference from the retention release, which
     * removes only audio and keeps the history. */
    DIR *d=opendir(directory);
    if(!d) return DISCARD_UNKNOWN;
    struct dirent *entry; char path[96]; unsigned removed=0;
    while((entry=readdir(d))) {
        if(entry->d_name[0]=='.') continue;
        /* Every name this device writes into a memo directory is short —
         * `00000000.M4A`, `COMPLETE.TXT`, the journal. A longer one did not come
         * from here, and building a path from it would either overflow or, worse,
         * silently truncate into a name that points at a different file. Skipped
         * rather than deleted; the rmdir below then fails and the whole discard
         * is refused, which is the right answer for a directory holding
         * something nobody here put there. */
        if(strlen(entry->d_name)>=32) continue;
        snprintf(path,sizeof(path),"%s/%.31s",directory,entry->d_name);
        if(unlink(path)==0) removed++;
    }
    closedir(d);
    if(rmdir(directory)!=0) return DISCARD_BROKEN;
    if(removed_out) *removed_out=removed;
    if(attention_out) *attention_out=attention;
    return DISCARD_DONE;
}

/* The counters are rebuilt from the card rather than adjusted by hand, so the
 * queue and the status bar cannot drift from what is actually there. */
static void refresh_queue_from_card(void) {
    memo_queue_scan();
    memo_queue_status queued=memo_queue_get();
    screen_status(queued.ready,queued.attention,queued.space_low);
    screen_status_storage_block(queued.space_block);
}

static void discard_memo(const char *id) {
    unsigned removed=0,attention=0;
    switch(discard_one(id,&removed,&attention)) {
        case DISCARD_DELIVERABLE: usb_line("@ERROR still_deliverable\n"); return;
        case DISCARD_UNKNOWN:     usb_line("@ERROR unknown_memo\n"); return;
        case DISCARD_BROKEN:      usb_line("@ERROR incomplete_discard\n"); return;
        case DISCARD_DONE: break;
    }
    char line[80];
    snprintf(line,sizeof(line),"@DISCARDED files=%u attention=%u\n",removed,attention);
    usb_line(line);
    ESP_LOGW("memo","session discarded on request; %u files, %u had needed attention",
             removed,attention);
    refresh_queue_from_card();
}

/* Discard every session that is eligible, in one command.
 *
 * Guarded by a count the caller has to supply, and it must match the number of
 * eligible sessions exactly. That is not ceremony: it forces the caller to have
 * looked at `memo-list` first, and it refuses if the card changed in between —
 * a recording finished while they were reading, say. A bare "delete everything"
 * with no number would be one stray line in a terminal away from destroying
 * recordings nobody meant to touch.
 *
 * Eligibility is per session and identical to the single-session rule: anything
 * still `ready` or `uploading` is skipped, never discarded, and reported. So
 * this command can never delete a recording that might still reach the server,
 * however large the number handed to it. */
#define DISCARD_ALL_MAX 64

static void discard_all(unsigned expected) {
    char ids[DISCARD_ALL_MAX][9];
    unsigned eligible=0,skipped=0,truncated=0;
    DIR *root=opendir("/sdcard/MEMOS");
    if(!root) { usb_line("@ERROR directory_unavailable\n"); return; }
    struct dirent *entry;
    while((entry=readdir(root))) {
        if(!memo_id_valid(entry->d_name)) continue;
        unsigned segments,ready,acked,attention; bool known;
        memo_states(entry->d_name,&segments,&ready,&acked,&attention,&known);
        if(known && ready) { skipped++; continue; }
        if(eligible>=DISCARD_ALL_MAX) { truncated++; continue; }
        memcpy(ids[eligible],entry->d_name,8); ids[eligible][8]=0; eligible++;
    }
    closedir(root);

    char line[120];
    if(expected!=eligible) {
        snprintf(line,sizeof(line),"@ERROR count_mismatch eligible=%u skipped=%u more=%u\n",
                 eligible,skipped,truncated);
        usb_line(line);
        return;
    }

    unsigned done=0,failed=0,files=0;
    for(unsigned i=0;i<eligible;i++) {
        unsigned removed=0,attention=0;
        if(discard_one(ids[i],&removed,&attention)==DISCARD_DONE) { done++; files+=removed; }
        else failed++;
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    snprintf(line,sizeof(line),"@DISCARDED sessions=%u files=%u failed=%u skipped=%u more=%u\n",
             done,files,failed,skipped,truncated);
    usb_line(line);
    ESP_LOGW("memo","bulk discard on request; %u sessions removed, %u refused, %u still deliverable",
             done,failed,skipped);
    refresh_queue_from_card();
}

/* Why a segment is marked, per segment, from the journal — including the reason
 * string that `mark()` recorded and whether the audio file is still on the card
 * and the size the journal expects. Without this the only way to explain 66
 * marked segments was inference from counters, which cost most of 6 September
 * and produced two wrong diagnoses. A `reason` field that is written but never
 * readable is not a diagnosis, it is a comment addressed to nobody.
 *
 * Purely reading: opens the journal and stats the files, touches nothing. */
static void explain_memo(const char *id) {
    if(!memo_id_valid(id)) { usb_line("@ERROR unknown_memo\n"); return; }
    char directory[40];
    snprintf(directory,sizeof(directory),"/sdcard/MEMOS/%s",id);
    journal_session *session=heap_caps_malloc(sizeof(journal_session),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!session) { usb_line("@ERROR no_memory\n"); return; }
    journal_session_init(session,directory);
    if(!journal_replay(session)) { free(session); usb_line("@ERROR unknown_memo\n"); return; }
    char line[192];
    snprintf(line,sizeof(line),
             "@WHY %.8s session=%.36s finished=%d segments=%u create_attention=%d create_reason=%s\n",
             id,session->session_id,session->finished?1:0,session->chunk_count,
             session->create_attention?1:0,
             session->create_attention&&session->create_reason[0]?session->create_reason:"-");
    usb_line(line);
    for(unsigned i=0;i<session->chunk_count;i++) {
        journal_chunk *chunk=&session->chunks[i];
        char path[112];
        snprintf(path,sizeof(path),"%s/%08u.M4A",directory,chunk->sequence);
        struct stat info;
        bool present=stat(path,&info)==0;
        snprintf(line,sizeof(line),
                 "@CHUNK %u %s reason=%s file=%s size=%llu expected=%llu\n",
                 chunk->sequence,journal_state_name(chunk->state),
                 chunk->reason[0]?chunk->reason:"-",
                 present?"present":"missing",
                 present?(unsigned long long)info.st_size:0ULL,
                 (unsigned long long)chunk->stored_length);
        if(!usb_line(line)) break;
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    free(session);
    usb_line("@DONE\n");
}

static void process_file_command(file_command *cmd) {
    if(cmd->discard_all) { discard_all(cmd->expected); return; }
    if(cmd->explain) { explain_memo(cmd->id); return; }
    if(cmd->discard) { discard_memo(cmd->id); return; }
    if(cmd->list) {
        DIR *d=opendir("/sdcard/MEMOS");
        if(!d) { usb_line("@ERROR directory_unavailable\n"); return; }
        struct dirent *entry;
        while((entry=readdir(d))) {
            /* The filter used to be `memo_info` alone, which requires a valid
             * COMPLETE.TXT — a file that exists only once a recording has ended
             * cleanly. So the listing showed exactly the healthy sessions and
             * hid every broken one, which is precisely backwards: the three
             * segments carrying `attention` sat in sessions that never appeared,
             * and their IDs could not be read off anywhere. A diagnostic command
             * that omits the damaged cases is worse than none, because it looks
             * like an all-clear.
             *
             * Now every directory with a plausible ID is listed. `memo_info`
             * still supplies segment count and duration where it can; where it
             * cannot, the journal supplies the segment count and the sample
             * count is reported as `?` rather than as zero. */
            if(!memo_id_valid(entry->d_name)) continue;
            unsigned segments=0; unsigned long long samples=0;
            bool complete=memo_info(entry->d_name,&segments,&samples);
            unsigned journal_segments,ready,acked,attention; bool known;
            memo_states(entry->d_name,&journal_segments,&ready,&acked,&attention,&known);
            if(!complete && !known) continue;   /* neither record: not a session */
            if(!complete) segments=journal_segments;
            char line[160];
            char duration[24];
            if(complete) snprintf(duration,sizeof(duration),"%llu",samples);
            else snprintf(duration,sizeof(duration),"? incomplete");
            if(known)
                snprintf(line,sizeof(line),"@MEMO %.8s %u %s ready=%u acked=%u attention=%u\n",
                         entry->d_name,segments,duration,ready,acked,attention);
            else
                snprintf(line,sizeof(line),"@MEMO %.8s %u %s ready=? acked=? attention=?\n",
                         entry->d_name,segments,duration);
            if(!usb_line(line)) break;
            vTaskDelay(pdMS_TO_TICKS(20));
        }
        closedir(d); usb_line("@DONE\n");
    } else {
        unsigned segments; unsigned long long samples;
        if(!memo_info(cmd->id,&segments,&samples)) { usb_line("@ERROR incomplete_or_missing_memo\n"); return; }
        char directory[40]; snprintf(directory,sizeof(directory),"/sdcard/MEMOS/%s",cmd->id);
        export_memo(directory,segments);
    }
}
static i2s_chan_handle_t rx;
static esp_codec_dev_handle_t mic;
// Only the recorder task accesses the writer and muxer state.
static bool writer_failed;
static void *file_open(char *path) {
    int fd=open(path,O_RDWR|O_CREAT|O_EXCL,0600);
    if(fd<0) { writer_failed=true; return NULL; }
    FILE *f=fdopen(fd,"w+b");
    if(!f) { close(fd); writer_failed=true; }
    return f;
}
static int file_write(void *f,void *data,int len) {
    int n=fwrite(data,1,len,f);
    if(n!=len) writer_failed=true;
    return n;
}
static int file_seek(void *f,uint64_t pos) {
    int r=fseek(f,(long)pos,SEEK_SET);
    if(r) writer_failed=true;
    return r;
}
static int file_close(void *f) {
    bool ok=fflush(f)==0;
    if(fsync(fileno(f))!=0) ok=false;
    if(fclose(f)!=0) ok=false;
    if(!ok) writer_failed=true;
    return ok?0:-1;
}
static int file_pattern(esp_muxer_slice_info_t *info,void *ctx) {
    if(info->slice_index!=0) return -1;
    int n=snprintf(info->file_path,info->len,"%s",(char *)ctx);
    return n>=0 && n<info->len ? 0:-1;
}
static bool init_mic(void) {
    // Waveshare S3_ePaper_3_97 mapping; speaker amplifier remains off.
    gpio_set_direction(39,GPIO_MODE_OUTPUT); gpio_set_level(39,0);
    i2c_master_bus_handle_t bus;
    i2c_master_bus_config_t i2c={.i2c_port=0,.sda_io_num=41,.scl_io_num=42,
        .clk_source=I2C_CLK_SRC_DEFAULT,.glitch_ignore_cnt=7,.flags.enable_internal_pullup=true};
    if(i2c_new_master_bus(&i2c,&bus)!=ESP_OK) return false;
    if(i2c_master_probe(bus,ES8311_CODEC_DEFAULT_ADDR>>1,100)!=ESP_OK) return false;
    i2s_chan_handle_t tx;
    i2s_chan_config_t channel=I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0,I2S_ROLE_MASTER);
    channel.dma_desc_num=12; channel.dma_frame_num=512;
    channel.auto_clear=true;
    if(i2s_new_channel(&channel,&tx,&rx)!=ESP_OK) return false;
    i2s_std_config_t std={.clk_cfg=I2S_STD_CLK_DEFAULT_CONFIG(48000),
        .slot_cfg=I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT,I2S_SLOT_MODE_STEREO),
        .gpio_cfg={.mclk=13,.bclk=14,.ws=47,.dout=48,.din=21}};
    if(i2s_channel_init_std_mode(tx,&std)!=ESP_OK || i2s_channel_init_std_mode(rx,&std)!=ESP_OK) return false;
    // Duplex master clocks are supplied by TX, even with ADC-only capture.
    if(i2s_channel_enable(tx)!=ESP_OK) return false;
    audio_codec_i2c_cfg_t control={.port=0,.addr=ES8311_CODEC_DEFAULT_ADDR,.bus_handle=bus};
    audio_codec_i2s_cfg_t data={.port=0,.rx_handle=rx,.tx_handle=tx};
    const audio_codec_ctrl_if_t *ctrl=audio_codec_new_i2c_ctrl(&control);
    const audio_codec_data_if_t *stream=audio_codec_new_i2s_data(&data);
    const audio_codec_gpio_if_t *gpio=audio_codec_new_gpio();
    if(!ctrl || !stream || !gpio) return false;
    es8311_codec_cfg_t codec={.ctrl_if=ctrl,.gpio_if=gpio,.codec_mode=ESP_CODEC_DEV_WORK_MODE_ADC,
        .pa_pin=-1,.use_mclk=true,.no_dac_ref=true};
    const audio_codec_if_t *chip=es8311_codec_new(&codec);
    if(!chip) return false;
    esp_codec_dev_cfg_t device={.dev_type=ESP_CODEC_DEV_TYPE_IN,.codec_if=chip,.data_if=stream};
    mic=esp_codec_dev_new(&device);
    bool ready = mic && esp_codec_dev_set_in_gain(mic,36.0)==ESP_CODEC_DEV_OK;
    /* Battery telemetry shares the board bus but is never allowed to make the
     * microphone unavailable. A missing or incompatible PMIC stays visibly
     * unknown and is inspectable with `battery-status`. */
    if (ready && !battery_start(bus))
        ESP_LOGW("memo", "battery telemetry unavailable; recording remains ready");
    return ready;
}
// Every journal write is durable before the audio it describes is relied upon.
// A failed append is a hard stop: recording without a record would be exactly
// the silent loss this stage exists to prevent.
static bool note(journal_session *session,const char *payload,int length) {
    if(length<=0 || !journal_append(session,payload,(size_t)length)) {
        ESP_LOGE("memo","journal append failed");
        return false;
    }
    return true;
}
// Below this, a BOOT-key hold is treated as an unintended button touch rather
// than a memo. Recording now starts on the first sampled press, so this guard
// remains the sole filter for stray or accidental captures.
#define MEMO_MIN_DURATION_MS 1500
static bool record_memo(bool diagnostic) {
    char dir[40],partial[64],final[64];
    memo_queue_update_space();
    memo_queue_status space=memo_queue_get();
    if(space.space_block) {
        ESP_LOGE("memo","card too full to start a recording; existing data untouched");
        screen_memo(SCREEN_ERROR,0);
        return false;
    }
    bool created=false;
    for(int i=0;i<8;i++) {
        snprintf(dir,sizeof(dir),"/sdcard/MEMOS/%08lx",(unsigned long)esp_random());
        if(mkdir(dir,0700)==0) { created=true; break; }
        if(errno!=EEXIST) break;
    }
    if(!created) return false;
    // The session identity exists on the card before the microphone opens, so
    // even a power loss during the first frame leaves a recoverable session.
    journal_session *journal=heap_caps_malloc(sizeof(journal_session),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!journal) { ESP_LOGE("memo","no memory for the session journal"); return false; }
    journal_session_init(journal,dir);
    char payload[JOURNAL_MAX_PAYLOAD],session_id[JOURNAL_UUID_CHARS];
    char context_id[JOURNAL_UUID_CHARS];
    portENTER_CRITICAL(&context_lock);
    snprintf(context_id,sizeof(context_id),"%s",clarification_context_id);
    portEXIT_CRITICAL(&context_lock);
    journal_uuid(session_id,memo_queue_random);
    if(!note(journal,payload,journal_build_session_context(payload,sizeof(payload),session_id,
            "auto",context_id[0]?"clarification":NULL,context_id[0]?context_id:NULL,MEMO_FIRMWARE,
            (uint64_t)(esp_timer_get_time()/1000),NULL,false))) {
        free(journal); return false;
    }
    void *encoder=NULL;
    esp_aac_enc_config_t config={.sample_rate=48000,.channel=1,.bits_per_sample=16,.bitrate=64000,.adts_used=false};
    if(esp_aac_enc_open(&config,sizeof(config),&encoder)!=ESP_AUDIO_ERR_OK) { free(journal); return false; }
    int in_size=0,out_size=0;
    esp_aac_enc_get_frame_size(encoder,&in_size,&out_size);
    int16_t *stereo=malloc(in_size*2),*mono=malloc(in_size);
    uint8_t *encoded=malloc(out_size);
    esp_codec_dev_sample_info_t fs={.sample_rate=48000,.channel=2,.bits_per_sample=16};
    bool opened=false,ok=stereo && mono && encoded && in_size>0 && out_size>0;
    if(ok) { opened=esp_codec_dev_open(mic,&fs)==ESP_CODEC_DEV_OK; ok=opened; }
    // Measured ES8311 ADC startup transient is confined to the first 100 ms.
    // Drain the settling samples before encoding, rather than storing the pop.
    for(int i=0;ok && i<5;i++) {
        size_t got=0;
        ok=i2s_channel_read(rx,stereo,in_size*2,&got,300)==ESP_OK && got==in_size*2;
    }
    uint64_t samples=0;
    unsigned sequence=0;
    int peak=0;
    int64_t start=esp_timer_get_time();
    // The initial prototype is limited to five minutes; no silent endless recording.
    unsigned limit=diagnostic?12:300;
    if(ok) {
        screen_memo(SCREEN_RECORDING,0);
        diagnostic_log_event(DIAG_EVENT_CAPTURE_START, 0, 0, 0);
    }
    ESP_LOGI("memo","capture start; diagnostic=%d",diagnostic);
    bool keep=ok;
    while(keep) {
        /* Decide before opening, not after. A segment is announced in the
         * journal before its first packet, deliberately, so an interrupted one
         * is discoverable at the next boot. But the loop used to open the next
         * segment without first asking whether recording was still wanted: a
         * memo released near a segment boundary announced a segment that then
         * received no audio, was never renamed into place, and came back from
         * recovery as `attention` — plus an error screen, for a recording that
         * had in fact been saved correctly. Nothing is announced now until the
         * recording is known to continue. */
        if(!(diagnostic || atomic_load(&held)) ||
           esp_timer_get_time()-start>=(int64_t)limit*1000000) break;
        snprintf(partial,sizeof(partial),"%s/%08u.TMP",dir,sequence);
        snprintf(final,sizeof(final),"%s/%08u.M4A",dir,sequence);
        // Chunk identity and start offset are durable before the first packet,
        // so an interrupted segment is always discoverable at the next boot.
        char chunk_id[JOURNAL_UUID_CHARS],name[16];
        uint64_t segment_start_ms=samples*1000/48000;
        journal_uuid(chunk_id,memo_queue_random);
        snprintf(name,sizeof(name),"%08u.M4A",sequence);
        if(!note(journal,payload,journal_build_chunk_open(payload,sizeof(payload),
                sequence,chunk_id,name,segment_start_ms))) { ok=false; break; }
        writer_failed=false;
        mp4_muxer_config_t cfg={.base_config={.muxer_type=ESP_MUXER_TYPE_MP4,
            .slice_duration=ESP_MUXER_MAX_SLICE_DURATION,.url_pattern_ex=file_pattern,
            .ctx=partial,.ram_cache_size=16384},.display_in_order=true};
        esp_muxer_handle_t mux=esp_muxer_open(&cfg.base_config,sizeof(cfg));
        if(!mux) { ok=false; break; }
        esp_muxer_file_writer_t writer={.on_open=file_open,.on_write=file_write,.on_seek=file_seek,.on_close=file_close};
        uint8_t asc[2]={0x11,0x88}; // MPEG-4 AAC-LC, 48 kHz, mono.
        esp_muxer_audio_stream_info_t info={.codec=ESP_MUXER_ADEC_AAC,.channel=1,.bits_per_sample=16,
            .sample_rate=48000,.min_packet_duration=21,.codec_spec_info=asc,.spec_info_len=2};
        int stream=0;
        ok=esp_muxer_set_file_writer(mux,&writer)==ESP_MUXER_ERR_OK &&
            esp_muxer_add_audio_stream(mux,&info,&stream)==ESP_MUXER_ERR_OK;
        unsigned frames=0;
        while(ok && frames<469) { // 10.005 seconds at 1024 samples/frame.
            size_t got=0;
            if(i2s_channel_read(rx,stereo,in_size*2,&got,300)!=ESP_OK || got!=in_size*2) { ok=false; break; }
            for(int i=0;i<in_size/2;i++) {
                mono[i]=stereo[i*2];
                int amplitude=abs((int)mono[i]); if(amplitude>peak) peak=amplitude;
            }
            esp_audio_enc_in_frame_t input={.buffer=(uint8_t *)mono,.len=in_size};
            esp_audio_enc_out_frame_t output={.buffer=encoded,.len=out_size};
            if(esp_aac_enc_process(encoder,&input,&output)!=ESP_AUDIO_ERR_OK) { ok=false; break; }
            esp_muxer_audio_packet_t packet={.data=encoded,.len=output.encoded_bytes,
                .pts=(uint32_t)((uint64_t)frames*(in_size/2)*1000/48000)};
            if(output.encoded_bytes && esp_muxer_add_audio_packet(mux,stream,&packet)!=ESP_MUXER_ERR_OK) { ok=false; break; }
            frames++; samples+=in_size/2;
            /* The recording indicator has no refresh rate of its own. It used
             * to be repainted on every second boundary, which on a 540 ms panel
             * meant the display was in motion for half of the recording — for a
             * seconds count nobody asked to see. The state is now set once when
             * recording starts and once when it ends; per the refresh policy in
             * docs/IMPLEMENTATION_DECISIONS.md anything that must keep moving
             * rides on the minute tick of the clock instead. `samples` keeps
             * being counted, because the saved message and the journal use it. */
            keep=(diagnostic || atomic_load(&held)) && esp_timer_get_time()-start<(int64_t)limit*1000000;
            if(!keep) break;
        }
        if(esp_muxer_close(mux)!=ESP_MUXER_ERR_OK || writer_failed) ok=false;
        if(ok && frames && rename(partial,final)!=0) ok=false;
        if(!ok) break; // Preserve incomplete files for inspection; never mark saved.
        // The digest is taken from the card, not from the encoder output, so a
        // write that did not survive the filesystem is caught here rather than
        // at upload time.
        journal_chunk *chunk=journal_find(journal,sequence);
        char digest[JOURNAL_SHA_CHARS]; uint64_t stored=0;
        if(!chunk || !memo_queue_hash(final,digest,&stored)) {
            ESP_LOGE("memo","segment unreadable after write"); ok=false; break;
        }
        chunk->plain_length=chunk->stored_length=stored;
        snprintf(chunk->plain_sha256,sizeof(chunk->plain_sha256),"%s",digest);
        snprintf(chunk->stored_sha256,sizeof(chunk->stored_sha256),"%s",digest);
        snprintf(chunk->encryption,sizeof(chunk->encryption),"none");
        chunk->source_start_ms=segment_start_ms;
        chunk->source_end_ms=samples*1000/48000;
        chunk->duration_ms=chunk->source_end_ms-segment_start_ms;
        if(!note(journal,payload,journal_build_chunk_ready(payload,sizeof(payload),chunk))) { ok=false; break; }
        memo_queue_note_ready(stored);
        sequence++;
    }
    if(opened && esp_codec_dev_close(mic)!=ESP_CODEC_DEV_OK) ok=false;
    esp_aac_enc_close(encoder); free(stereo); free(mono); free(encoded);
    /* A touch that only briefly pressed the BOOT key still reaches here
     * with a cleanly closed, possibly zero-segment recording — the directory
     * and its session record were already written before the microphone ever
     * opened. Below this duration it is treated as an unintended press, not a
     * memo: discarded outright rather than left as a stub or a near-silent
     * segment. Safe to remove unconditionally, unlike `discard_one()` — this
     * directory was created earlier in this very call and has not been
     * offered to the sync worker yet, so nothing can be "deliverable" here. */
    if(ok && samples*1000/48000<MEMO_MIN_DURATION_MS) {
        /* Every completed segment above already ran memo_queue_note_ready(),
         * which put it in the `ready` bucket the status bar counts. Deleting
         * the files without leaving that bucket the same way it is normally
         * left (mark_chunk() -> memo_queue_note_transition()) would strand
         * the counter above zero forever — the exact cache-drift failure
         * memo_queue.c's own history warns about, just for `ready` instead
         * of `attention` this time. */
        for(unsigned i=0;i<sequence;i++) memo_queue_note_transition(CHUNK_READY,CHUNK_UNKNOWN);
        free(journal);
        DIR *d=opendir(dir);
        if(d) {
            struct dirent *entry; char path[96];
            while((entry=readdir(d))) {
                if(entry->d_name[0]=='.') continue;
                if(strlen(entry->d_name)>=32) continue;
                snprintf(path,sizeof(path),"%s/%.31s",dir,entry->d_name);
                unlink(path);
            }
            closedir(d);
            rmdir(dir);
        }
        ESP_LOGI("memo","recording too short (%llu ms); discarded, not offered",
                 (unsigned long long)(samples*1000/48000));
        diagnostic_log_event(DIAG_EVENT_CAPTURE_END, 1, 0, 0);
        return true;
    }
    if(ok && sequence) {
        snprintf(partial,sizeof(partial),"%s/COMPLETE.TMP",dir);
        snprintf(final,sizeof(final),"%s/COMPLETE.TXT",dir);
        FILE *f=file_open(partial);
        if(!f) ok=false;
        else {
            if(fprintf(f,"local_memo_v1\nsegments=%u\nsamples=%llu\nsample_rate=48000\n",sequence,(unsigned long long)samples)<0) ok=false;
            if(file_close(f)!=0) ok=false;
            if(ok && rename(partial,final)!=0) ok=false;
        }
    }
    // finish closes the local horizon only. Nothing is deleted here; audio
    // leaves the card no earlier than a persisted durable ACK in H2.
    //
    // Written whenever segments exist, deliberately without regard to `ok`.
    // `sequence` counts only segments that were renamed into place, hashed from
    // the card and journaled as `ready`, so it always states what genuinely
    // exists. Tying the record to `ok` meant that a failure anywhere after the
    // last good segment — a muxer close, an unwritable COMPLETE.TXT, even the
    // microphone refusing to close — left the session permanently open: every
    // segment delivered and acknowledged, but no final sequence, so the upload
    // pass re-created it on every sync and it could never be marked complete.
    // The failure still shows: `ok` alone decides between the saved and the
    // error screen.
    // Never `ok=`: a failure earlier in the recording must survive this line,
    // or a session that broke would be reported as saved.
    if(sequence && !note(journal,payload,journal_build_finish(payload,sizeof(payload),
            sequence-1,samples*1000/48000)))
        ok=false;
    unsigned ready=journal_count_state(journal,CHUNK_READY);
    unsigned attention=journal_count_state(journal,CHUNK_ATTENTION);
    free(journal);
    if(sequence && context_id[0]) {
        screen_clarification_answered(context_id);
        portENTER_CRITICAL(&context_lock);
        if(strcmp(clarification_context_id,context_id)==0)
            clarification_context_id[0]=0;
        portEXIT_CRITICAL(&context_lock);
    }
    if(ok && diagnostic) { strcpy(diagnostic_dir,dir); diagnostic_segments=sequence; }
    memo_queue_update_space();
    space=memo_queue_get();
    screen_status(space.ready,space.attention,space.space_low);
    screen_status_storage_block(space.space_block);
    ESP_LOGI("memo","capture %s; segments=%u ready=%u attention=%u samples=%llu peak=%d stack_free=%u heap_internal=%u",
        ok?"SAVED":"FAILED",sequence,ready,attention,(unsigned long long)samples,peak,
        (unsigned)uxTaskGetStackHighWaterMark(NULL),(unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
    diagnostic_log_event(DIAG_EVENT_CAPTURE_END, ok ? 1 : 0,
                         (int)sequence, 0);
    screen_memo(ok?SCREEN_MEMO_SAVED:SCREEN_ERROR,(unsigned)(samples/48000));
    return ok;
}
static void recorder_task(void *unused) {
    bool storage_ok = storage_check();
    if (storage_ok) diagnostic_log_start();
    bool ok=storage_ok && (mkdir("/sdcard/MEMOS",0700)==0 || errno==EEXIST) && init_mic();
    if(ok) ok=mp4_muxer_register()==ESP_MUXER_ERR_OK;
    if(!ok) {
        ESP_LOGE("memo","initialization failed"); screen_memo(SCREEN_ERROR,0); vTaskDelete(NULL); return;
    }
    // Boot recovery runs before the device claims to be ready: every segment on
    // the card is verified and classified first, so READY is an honest state.
    memo_queue_scan();
    memo_queue_status queued=memo_queue_get();
    diagnostic_log_event(DIAG_EVENT_STORAGE, 1,
                         (int)(queued.bytes_free / (1024 * 1024)),
                         (int)(queued.bytes_total / (1024 * 1024)));
    diagnostic_log_event(DIAG_EVENT_QUEUE, (int)queued.ready,
                         (int)queued.acked, (int)queued.attention);
    screen_status(queued.ready,queued.attention,queued.space_low);
    screen_status_storage_block(queued.space_block);
    screen_memo(SCREEN_READY,0);
    ESP_LOGI("memo","READY; hold BOOT button GPIO0 to record");
    while(true) {
        /* Upload state is journal truth, while the status bar uses a small RAM
         * cache. Rebuild that cache after a completed state-changing upload
         * pass. The request is handled here, not in the API task, so journal
         * recovery can never race a new recording's file writes. Multiple
         * transitions in one pass collapse into one scan. */
        if(atomic_exchange(&queue_rescan_requested,false)) {
            atomic_store(&busy,true);
            refresh_queue_from_card();
            atomic_store(&busy,false);
        }
        if(atomic_exchange(&export_requested,false)) export_memo(diagnostic_dir,diagnostic_segments);
        file_command cmd;
        if(xQueueReceive(file_commands,&cmd,0)==pdTRUE) {
            atomic_store(&busy,true);
            process_file_command(&cmd);
            atomic_store(&busy,false);
        }
        bool diagnostic=atomic_exchange(&test_requested,false);
        if(diagnostic || atomic_load(&held)) {
            atomic_store(&busy,true);
            bool saved=record_memo(diagnostic);
            if(!saved) screen_memo(SCREEN_ERROR,0);
            while(atomic_load(&held)) vTaskDelay(pdMS_TO_TICKS(20));
            // A new press can skip the confirmation delay without losing its start.
            for(int i=0;i<150 && !atomic_load(&held);i++) vTaskDelay(pdMS_TO_TICKS(20));
            atomic_store(&busy,false);
            /* Wake the uploader only after the recorder has released the SD
             * card.  Waking it inside record_memo() races with recorder_busy()
             * and can strand a freshly saved memo until the next reconnect. */
            if(saved) api_client_queue_changed();
            if(saved) screen_memo(SCREEN_READY,0);
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}
void recorder_start(void) {
    file_commands=xQueueCreate(2,sizeof(file_command));
    if(!file_commands) { screen_memo(SCREEN_ERROR,0); return; }
    if(xTaskCreate(recorder_task,"memo",49152,NULL,5,NULL)!=pdPASS) {
        ESP_LOGE("memo","task allocation failed"); screen_memo(SCREEN_ERROR,0);
    }
}
void recorder_hold(bool value) { atomic_store(&held,value); }
void recorder_set_clarification_context(const char *question_id) {
    portENTER_CRITICAL(&context_lock);
    snprintf(clarification_context_id,sizeof(clarification_context_id),"%s",question_id?question_id:"");
    portEXIT_CRITICAL(&context_lock);
}
void recorder_test(void) { if(!atomic_load(&busy)) atomic_store(&test_requested,true); }
void recorder_export_test(void) { if(!atomic_load(&busy)) atomic_store(&export_requested,true); }
void recorder_discard_all(unsigned expected) {
    file_command cmd={.discard_all=true,.expected=expected};
    if(!file_commands || atomic_load(&busy) || xQueueSend(file_commands,&cmd,0)!=pdTRUE)
        usb_line("@ERROR busy_or_unavailable\n");
}
void recorder_explain(const char *id) {
    file_command cmd={.explain=true};
    if(!memo_id_valid(id)) { usb_line("@ERROR invalid_id\n"); return; }
    memcpy(cmd.id,id,8);
    if(!file_commands || atomic_load(&busy) || xQueueSend(file_commands,&cmd,0)!=pdTRUE)
        usb_line("@ERROR busy_or_unavailable\n");
}
void recorder_discard(const char *id) {
    file_command cmd={.discard=true};
    if(!memo_id_valid(id)) { usb_line("@ERROR invalid_id\n"); return; }
    memcpy(cmd.id,id,8);
    if(!file_commands || atomic_load(&busy) || xQueueSend(file_commands,&cmd,0)!=pdTRUE)
        usb_line("@ERROR busy_or_unavailable\n");
}
void recorder_files(const char *id) {
    file_command cmd={.list=id==NULL};
    if(id) {
        if(!memo_id_valid(id)) { usb_line("@ERROR invalid_id\n"); return; }
        memcpy(cmd.id,id,8);
    }
    if(!file_commands || atomic_load(&busy) || xQueueSend(file_commands,&cmd,0)!=pdTRUE)
        usb_line("@ERROR busy_or_unavailable\n");
}
bool recorder_busy(void) { return atomic_load(&busy) || atomic_load(&held); }
// Counts and reasons only: no file names, no audio, no credentials.
void recorder_queue_status(void) {
    memo_queue_status queued=memo_queue_get();
    char line[200];
    snprintf(line,sizeof(line),
        "@QUEUE scanned=%d sessions=%u adopted=%u closed=%u ready=%u acked=%u attention=%u "
        "free_mb=%llu total_mb=%llu space_low=%d space_block=%d\n",
        queued.scanned?1:0,queued.sessions,queued.adopted,queued.closed,queued.ready,queued.acked,
        queued.attention,(unsigned long long)(queued.bytes_free/(1024*1024)),
        (unsigned long long)(queued.bytes_total/(1024*1024)),
        queued.space_low?1:0,queued.space_block?1:0);
    usb_line(line);
}
void recorder_request_queue_rescan(void) { atomic_store(&queue_rescan_requested,true); }
