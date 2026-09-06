package com.smartnotebook.service.recording

public object RecordingControllerRegistry {
    @Volatile
    private var current: RecordingControl? = null

    @Synchronized
    public fun register(control: RecordingControl) {
        current = control
    }

    @Synchronized
    public fun unregister(control: RecordingControl) {
        if (current === control) {
            current = null
        }
    }

    @Synchronized
    public fun current(): RecordingControl? = current
}
