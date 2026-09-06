-keepattributes *Annotation*, Signature, InnerClasses, EnclosingMethod, Deprecated, Exceptions

-keep,includedescriptorclasses class com.smartnotebook.**$$serializer { *; }

-keepclassmembers class com.smartnotebook.** {
    *** Companion;
}

-keepclasseswithmembers class com.smartnotebook.** {
    kotlinx.serialization.KSerializer serializer(...);
}
