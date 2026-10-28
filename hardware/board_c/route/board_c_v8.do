# Board C v8: as v7, with plane fanouts that respect same-net via stacking (and may share a neighbour's via).
unit mm
rule pcb (clearance 0.13 (type via_via via_smd via_pin via_wire))
set edge_clearance 0.5
set max_expansions 6000000
status_file $/board_c_v8.sts
bestsave on $/board_c_v8_best.ses
read session $/board_c_v7_resume.ses
route 3 6
route 3 12
route 3 16
route 2 22
route 2 25
clean 1
miter
write session $/board_c_v8.ses
report status $/board_c_v8_status.txt
quit
