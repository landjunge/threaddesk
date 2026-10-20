# Error-page layout measurement

The main installer acceptance run39455422366 failed one layout case after an
invalid ZIP upload (936 passed). The other main tests and all three installer
builds were green; that failed installer acceptance remains historical evidence.

The test waited for a visible error alert after the restore POST, then measured
control heights immediately. A completed click and visible alert do not mean
the new document's stylesheets have loaded. The test now binds explicitly to
that fresh navigation, waits for its `load`, and checks the HTTP400 response
before measuring. No product file, CSS value or timeout changes.

Own private controlled test, macOS Chromium151:

- Hold all three CSS responses for the actual invalid-ZIP HTML response.
  Before the barrier, click completes and alert is visible while every stylesheet
  is absent: links18px/buttons21px and black Thread text. The Linux CI links
  were17px. An HTTP200 control with the same error body behaves the same way.
- With the navigation barrier, its task remains pending while those CSS
  responses are held. Only releasing them completes the fresh POST400
  navigation; every control is40px and the existing violet wordmark returns.
- The affected repository browser test passes (1/1). No arbitrary sleep,
  timeout extension, product recoloring or blind full-suite retry.

This reproduces the timing mechanism; the original CI run did not capture its
stylesheet timeline. It does not identify which screen the user's separate
color feedback referred to. Final CI is a separate gate.
