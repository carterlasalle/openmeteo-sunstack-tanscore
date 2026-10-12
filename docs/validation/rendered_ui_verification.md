# Rendered-UI verification (Phase 2 acceptance)

Artifact: `docs` · checks: **49/49 passed**

Driven by real Chromium over the committed static export (`uv run --with playwright python scripts/verify_rendered_ui.py`).

Screenshots: `docs/validation/rendered_ui/` (desktop-1350.png, mobile-390.png).

| check | result | observed |
|---|---|---|
| [desktop 1350px] no horizontal page overflow | PASS | `{'inner': 1350, 'doc': 1350, 'body': 1350}` |
| [desktop 1350px] page loads with a payload and no console/page errors | PASS | `Tuesday, October 13 is the best day in this run. Best window 1:30 PM – 2 PM — 1099 J/m² pigment-weighted dose (confidenc` |
| [desktop 1350px] flat/unknown pose states the horizontal-reference invariant | PASS | ` dose (confidence 44). This number is the horizontal reference for this location — surface, tilt and skin type change your exposure, not it.` |
| [desktop 1350px] material+tilt reach the hero above the fold | PASS | `['On Dry beach sand, tilted 45° that becomes 1628 J/m² in your plane (+48%).']` |
| [desktop 1350px] panel plane factor equals the physics module (4-dp round) | PASS | `page=0.943719 module=0.943700 row=2026-10-12T13:30` |
| [desktop 1350px] panel names its row and reports the gain | PASS | `Surface Dry beach sand at 2026-10-12 13:30 (computed in your browser) · reflectance proxy 16.50% · reflected UVA 0.73 W/m² · reflected UVB 0.02 W/m² · tilt 45° ` |
| [desktop 1350px] schedule is marked environmental-only, not silently inert | PASS | `One block per line — Mon 11:00-12:15. Kept in this browser only; it is never part of the published forecast. With no schedule entered, nothing is filtered and no class ro` |
| [desktop 1350px] personal MMD is hidden with a stated reason | PASS | `Personal MMD needs the live server — this page ships one published run.` |
| [desktop 1350px] ranking row agrees with the payload: Dose J/m² | PASS | `shown=960 payload=960.354` |
| [desktop 1350px] ranking row agrees with the payload: Overall | PASS | `shown=38 payload=37.6` |
| [desktop 1350px] ranking row agrees with the payload: Abs | PASS | `shown=30 payload=29.8` |
| [desktop 1350px] ranking row agrees with the payload: Local | PASS | `shown=92 payload=92.2` |
| [desktop 1350px] day card shows the dose and the window that dose came from | PASS | `['dose=1088.3', '1:30 PM', '2 PM', 'Mon, 10/12FAIR1:30 PM – 2 PMsustained 11:30 AM – 3:30 PM1088 J/m²Fit 100%Conf 39']` |
| [desktop 1350px] Dose/Overall/Abs/Local are shown together with distinguishing semantics | PASS | `['Abs', 'Atm', 'CAMS', 'Clear', 'Cloud', 'Conf', 'DNI', 'Dose J/m²', 'EPA', 'Local', 'Note', 'OM', 'Overall', 'Rain', 'Source', 'Sun', 'Temp °F', 'Time', 'UVA', 'UVB', 'UV∘', 'Wind mph', 'ΔUV']` |
| [desktop 1350px] days with no usable window say so in their card (4 of them) | PASS | `['2026-10-16', '2026-10-17']` |
| [desktop 1350px] times state the site timezone on the rendered page | PASS | `Times are shown in the site zone: America/Indiana/Indianapolis (EDT). Your schedule is read in the same zone.` |
| [desktop 1350px] Tier-C is labelled a fixed-band proxy where the number is shown | PASS | `['ipped action spectra, not a per-wavelength convolution, so absolute dose is a proxy scale.', 'The fixed-band proxy is biased a median +204% against true spectra (p05-p95 +141.6% to +23']` |
| [desktop 1350px] UVI fusion names its non-independent reference (baseline + limitation) | PASS | `['basis=True', 'limit=True', 'nTitles=2', 'y in the page — hidden ones are one tap away and always in Export CSV.']` |
| [desktop 1350px] rank and score semantics carry their versions where they are read | PASS | `['Surface Dry beach sand at 2026-10-12 13:30 (computed in your browser) ', ', not a per-wavelength convolution, so absolute dose is a proxy scale.']` |
| [desktop 1350px] confidence is labelled a heuristic, not a calibrated interval | PASS | `['Heuristic reliability 0–100 — discounted when sources disagree; expect', '0-100 heuristic reliability estimate, not an empirically calibrated in']` |
| [desktop 1350px] site picker carries the other site as a link, not an in-place switch | PASS | `['south-bend/', 'pacific-palisades/sites/pacific-palisades/']` |
| [desktop 1350px] a day with no usable window says so instead of showing 0 J/m² as fine | PASS | `Monday, October 12 — NO USABLE WINDOW on this day. This is missing usable light, not zero radiation.` |
| [desktop 1350px] site picker navigates to the other site's own page and payload | PASS | `http://127.0.0.1:54506/sites/pacific-palisades/?location=pacific-palisades&date=2026-10-12 :: Thursday, October 15 is the best day in this run. Best window 12:30 PM – 1 PM — 1556 J/m² ` |
| [desktop 1350px] calendar link is the published .ics, never the live API path | PASS | `webcal://127.0.0.1:54506/calendar.ics` |
| [mobile 390px] no horizontal page overflow | PASS | `{'inner': 390, 'doc': 390, 'body': 390}` |
| [mobile 390px] page loads with a payload and no console/page errors | PASS | `Tuesday, October 13 is the best day in this run. Best window 1:30 PM – 2 PM — 1099 J/m² pigment-weighted dose (confidenc` |
| [mobile 390px] flat/unknown pose states the horizontal-reference invariant | PASS | ` dose (confidence 44). This number is the horizontal reference for this location — surface, tilt and skin type change your exposure, not it.` |
| [mobile 390px] material+tilt reach the hero above the fold | PASS | `['On Dry beach sand, tilted 45° that becomes 1628 J/m² in your plane (+48%).']` |
| [mobile 390px] panel plane factor equals the physics module (4-dp round) | PASS | `page=0.943719 module=0.943700 row=2026-10-12T13:30` |
| [mobile 390px] panel names its row and reports the gain | PASS | `Surface Dry beach sand at 2026-10-12 13:30 (computed in your browser) · reflectance proxy 16.50% · reflected UVA 0.73 W/m² · reflected UVB 0.02 W/m² · tilt 45° ` |
| [mobile 390px] schedule is marked environmental-only, not silently inert | PASS | `One block per line — Mon 11:00-12:15. Kept in this browser only; it is never part of the published forecast. With no schedule entered, nothing is filtered and no class ro` |
| [mobile 390px] personal MMD is hidden with a stated reason | PASS | `Personal MMD needs the live server — this page ships one published run.` |
| [mobile 390px] ranking row agrees with the payload: Dose J/m² | PASS | `shown=960 payload=960.354` |
| [mobile 390px] ranking row agrees with the payload: Overall | PASS | `shown=38 payload=37.6` |
| [mobile 390px] ranking row agrees with the payload: Abs | PASS | `shown=30 payload=29.8` |
| [mobile 390px] ranking row agrees with the payload: Local | PASS | `shown=92 payload=92.2` |
| [mobile 390px] day card shows the dose and the window that dose came from | PASS | `['dose=1088.3', '1:30 PM', '2 PM', 'Mon, 10/12FAIR1:30 PM – 2 PMsustained 11:30 AM – 3:30 PM1088 J/m²Fit 100%Conf 39']` |
| [mobile 390px] Dose/Overall/Abs/Local are shown together with distinguishing semantics | PASS | `['Abs', 'Atm', 'CAMS', 'Clear', 'Cloud', 'Conf', 'DNI', 'Dose J/m²', 'EPA', 'Local', 'Note', 'OM', 'Overall', 'Rain', 'Source', 'Sun', 'Temp °F', 'Time', 'UVA', 'UVB', 'UV∘', 'Wind mph', 'ΔUV']` |
| [mobile 390px] days with no usable window say so in their card (4 of them) | PASS | `['2026-10-16', '2026-10-17']` |
| [mobile 390px] times state the site timezone on the rendered page | PASS | `Times are shown in the site zone: America/Indiana/Indianapolis (EDT). Your schedule is read in the same zone.` |
| [mobile 390px] Tier-C is labelled a fixed-band proxy where the number is shown | PASS | `['ipped action spectra, not a per-wavelength convolution, so absolute dose is a proxy scale.', 'The fixed-band proxy is biased a median +204% against true spectra (p05-p95 +141.6% to +23']` |
| [mobile 390px] UVI fusion names its non-independent reference (baseline + limitation) | PASS | `['basis=True', 'limit=True', 'nTitles=2', 'y in the page — hidden ones are one tap away and always in Export CSV.']` |
| [mobile 390px] rank and score semantics carry their versions where they are read | PASS | `['Surface Dry beach sand at 2026-10-12 13:30 (computed in your browser) ', ', not a per-wavelength convolution, so absolute dose is a proxy scale.']` |
| [mobile 390px] confidence is labelled a heuristic, not a calibrated interval | PASS | `['Heuristic reliability 0–100 — discounted when sources disagree; expect', '0-100 heuristic reliability estimate, not an empirically calibrated in']` |
| [mobile 390px] site picker carries the other site as a link, not an in-place switch | PASS | `['south-bend/', 'pacific-palisades/sites/pacific-palisades/']` |
| [mobile 390px] a day with no usable window says so instead of showing 0 J/m² as fine | PASS | `Monday, October 12 — NO USABLE WINDOW on this day. This is missing usable light, not zero radiation.` |
| [mobile 390px] site picker navigates to the other site's own page and payload | PASS | `http://127.0.0.1:54506/sites/pacific-palisades/?location=pacific-palisades&date=2026-10-12 :: Thursday, October 15 is the best day in this run. Best window 12:30 PM – 1 PM — 1556 J/m² ` |
| [mobile 390px] calendar link is the published .ics, never the live API path | PASS | `webcal://127.0.0.1:54506/calendar.ics` |
| [mobile 390px] pixel baseline compared | PASS | `skipped: Pillow not installed` |
