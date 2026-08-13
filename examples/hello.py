# Attach to a real tab in the running Chrome window and print what we see.
tab = ensure_real_tab()
print("ATTACHED")
print(page_info())
print("TABS")
for t in list_tabs(include_chrome=False):
    print(t)
