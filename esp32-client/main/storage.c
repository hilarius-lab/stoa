#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <inttypes.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include "driver/sdmmc_host.h"
#include "sdmmc_cmd.h"
#include "esp_vfs_fat.h"
#include "esp_random.h"
#include "esp_log.h"
#include "storage.h"

bool storage_check(void) {
    // Waveshare 04_SD_Test pin map. Never format on any mount failure.
    sdmmc_host_t host = SDMMC_HOST_DEFAULT();
    host.max_freq_khz = SDMMC_FREQ_DEFAULT;
    sdmmc_slot_config_t slot = SDMMC_SLOT_CONFIG_DEFAULT();
    slot.width=4; slot.clk=16; slot.cmd=17;
    slot.d0=15; slot.d1=7; slot.d2=8; slot.d3=18;
    esp_vfs_fat_sdmmc_mount_config_t config = {
        .format_if_mount_failed=false, .max_files=5, .allocation_unit_size=32768
    };
    sdmmc_card_t *card=NULL;
    esp_err_t err=esp_vfs_fat_sdmmc_mount("/sdcard",&host,&slot,&config,&card);
    if(err!=ESP_OK) { ESP_LOGE("storage","mount failed: %s; no format attempted",esp_err_to_name(err)); return false; }
    uint64_t total=0,available=0;
    err=esp_vfs_fat_info("/sdcard",&total,&available);
    if(err!=ESP_OK) { ESP_LOGE("storage","capacity failed: %s",esp_err_to_name(err)); return false; }
    ESP_LOGI("storage","mounted; total=%" PRIu64 " free=%" PRIu64 " bytes",total,available);
    if(mkdir("/sdcard/SNTEST",0700)!=0 && errno!=EEXIST) {
        ESP_LOGE("storage","test directory unavailable"); return false;
    }
    // 8.3 filename, exclusive creation: never truncate a pre-existing file.
    char path[40]; int fd=-1;
    for(int attempt=0;attempt<8;attempt++) {
        snprintf(path,sizeof(path),"/sdcard/SNTEST/%08" PRIX32 ".TMP",esp_random());
        fd=open(path,O_WRONLY|O_CREAT|O_EXCL,0600);
        if(fd>=0 || errno!=EEXIST) break;
    }
    if(fd<0) { ESP_LOGE("storage","test create failed errno=%d",errno); return false; }
    uint8_t expected[512],actual[512];
    for(unsigned i=0;i<sizeof(expected);i++) expected[i]=(uint8_t)(i*37+11);
    bool ok=write(fd,expected,sizeof(expected))==sizeof(expected);
    if(ok) ok=fsync(fd)==0;
    if(close(fd)!=0) ok=false;
    if(ok) {
        fd=open(path,O_RDONLY);
        if(fd<0) ok=false;
        else {
            ok=read(fd,actual,sizeof(actual))==sizeof(actual) && memcmp(actual,expected,sizeof(actual))==0;
            uint8_t extra; if(ok) ok=read(fd,&extra,1)==0;
            if(close(fd)!=0) ok=false;
        }
    }
    // Only this successfully created file is removed; existing directory retained.
    bool cleaned=unlink(path)==0;
    ESP_LOGI("storage","write_sync_read_compare=%s cleanup=%s",ok?"PASS":"FAIL",cleaned?"PASS":"FAIL");
    return ok && cleaned;
}
