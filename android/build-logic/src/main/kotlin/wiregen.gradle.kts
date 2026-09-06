import com.smartnotebook.buildlogic.wiregen.WireGenGenerateTask
import com.smartnotebook.buildlogic.wiregen.WireGenVerifyTask

val wireSnapshot = rootProject.projectDir.parentFile.resolve("contracts/client-openapi-v1.json")
val wireGeneratedSourceDir =
    layout.projectDirectory.dir("src/main/kotlin/com/smartnotebook/core/network/wire/generated")

tasks.register<WireGenGenerateTask>("generateWireDtos") {
    group = "wiregen"
    description = "Generiert Wire-DTOs aus dem OpenAPI-Snapshot nach build/wiregen/generated."
    snapshot.set(wireSnapshot)
    outputDir.set(layout.buildDirectory.dir("wiregen/generated"))
}

val verifyWireDtos = tasks.register<WireGenVerifyTask>("verifyWireDtos") {
    group = "verification"
    description = "Drift-Gate: prueft, dass die gecheckten Wire-DTOs mit dem OpenAPI-Snapshot ubereinstimmen."
    snapshot.set(wireSnapshot)
    sourceDir.set(wireGeneratedSourceDir)
}

tasks.named("check") {
    dependsOn(verifyWireDtos)
}
