from smart_notebook.services.audio import _looks_like_continuation

assert _looks_like_continuation("auf die Einkaufsliste.")
assert _looks_like_continuation("und anschließend archivieren.")
assert _looks_like_continuation("drei weitere Punkte.")
assert not _looks_like_continuation("Über den Anbieter entscheiden wir später.")
assert not _looks_like_continuation("Der nächste Tagesordnungspunkt beginnt.")
print("TRANSCRIPT CONTINUATION TEST: PASS")
