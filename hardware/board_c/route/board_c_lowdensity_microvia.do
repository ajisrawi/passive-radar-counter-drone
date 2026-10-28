# OpenRoute script for the low-density OpenBoard redesign of Board C with blind/buried vias (spans from the project rules)
# checkpoint (bestsave) after every 3 passes
# KiCad hole clearance 0.25 mm met by 0.13 mm via clearances; 0.5 mm copper to edge.
unit mm
rule pcb (clearance 0.13 (type via_via via_smd via_pin via_wire))
set edge_clearance 0.5
status_file $/board_c_lowdensity_microvia.sts
bestsave on $/board_c_lowdensity_microvia_best.ses
fanout
route 3
route 3 4
route 3 7
route 3 10
route 3 13
route 3 16
route 3 19
route 3 22
clean 1
write session $/board_c_lowdensity_microvia.ses
report status $/board_c_lowdensity_microvia_status.txt
report conflicts $/board_c_lowdensity_microvia_drc.txt
quit
