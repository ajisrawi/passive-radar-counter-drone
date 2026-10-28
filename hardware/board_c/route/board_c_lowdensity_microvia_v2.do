# Board C low-density microvia redesign, rerouted with the fixed router (pad rotation, symmetric via spacing,
# same-net via stacking/spacing, redundant-via merge, imported-copper-safe clean, best-only bestsave).
# Resumes from the previous best copper: anything that breaks the new rules counts as a conflict and is rerouted.
unit mm
rule pcb (clearance 0.13 (type via_via via_smd via_pin via_wire))
set edge_clearance 0.5
status_file $/board_c_lowdensity_microvia_v2.sts
bestsave on $/board_c_lowdensity_microvia_v2_best.ses
read session $/board_c_lowdensity_microvia_extra.ses
route 3 10
route 3 13
route 3 16
route 3 19
route 3 22
route 3 25
clean 1
miter
write session $/board_c_lowdensity_microvia_v2.ses
report status $/board_c_lowdensity_microvia_v2_status.txt
quit
