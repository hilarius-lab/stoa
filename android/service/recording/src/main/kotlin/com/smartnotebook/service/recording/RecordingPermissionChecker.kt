package com.smartnotebook.service.recording

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import com.smartnotebook.core.model.ClientErrorCode

public interface RecordingPermissionChecker {
    public fun requiredPermissionCode(): ClientErrorCode?
}

public class AndroidRecordingPermissionChecker(
    private val context: Context,
) : RecordingPermissionChecker {
    @Suppress("ReturnCount")
    override fun requiredPermissionCode(): ClientErrorCode? {
        if (context.checkSelfPermission(RECORD_AUDIO_PERMISSION) != PackageManager.PERMISSION_GRANTED) {
            return ClientErrorCode.MIC_PERMISSION_REQUIRED
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            context.checkSelfPermission(POST_NOTIFICATIONS_PERMISSION) != PackageManager.PERMISSION_GRANTED
        ) {
            return ClientErrorCode.NOTIFICATION_PERMISSION_REQUIRED
        }

        return null
    }

    private companion object {
        const val RECORD_AUDIO_PERMISSION = "android.permission.RECORD_AUDIO"
        const val POST_NOTIFICATIONS_PERMISSION = "android.permission.POST_NOTIFICATIONS"
    }
}
