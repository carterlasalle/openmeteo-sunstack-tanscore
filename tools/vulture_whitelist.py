"""Names vulture reports as unused with no way to see the use.

Positional argument on purpose: vulture requires the whitelist BEFORE
--min-confidence, and reading it is the reason the numbers here are not a
judgement call.

Kept narrow: each entry is a Protocol stub parameter (body is `...`) whose
callers pass it by keyword across the script boundary, so there is no local
reference for vulture to find. A real dead local in the same module would be
reported exactly as before - the whitelist exempts the NAME, and these four are
only ever parameters of an interface.
"""

unit_scale
station
argv
corpus_dir
pred_uvb
true_uvb
regime_ids
data_path
pred_emel
pred_ery
pred_uva
true_emel
true_ery
true_uva# Used only inside a string annotation: cast("httpx.Client", ...). Vulture does
# not parse annotations, the import is real.
httpx

# cdsapi.Client's keyword parameters, declared in the _CdsModule Protocol stub
# above the call site in history.py.
quiet
wait_until_complete
