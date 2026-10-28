# OpenRoute script for the OpenBoard redesign of Board C (auto-placed, original rules)
# KiCad hole clearance 0.25 mm met by 0.13 mm via clearances; 0.5 mm copper to edge.
unit mm
rule pcb (clearance 0.13 (type via_via via_smd via_pin via_wire))
set edge_clearance 0.5
status_file $/board_c_lowdensity.sts
bestsave on $/board_c_lowdensity_best.ses
fanout
route 5
route 5 6
route 5 11
route 5 16
route 5 21
clean 1
write session $/board_c_lowdensity.ses
report status $/board_c_lowdensity_status.txt
report conflicts $/board_c_lowdensity_drc.txt
quit
