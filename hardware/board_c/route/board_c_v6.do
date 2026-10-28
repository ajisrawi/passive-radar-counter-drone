# Board C v6: one more resume round from v5 for the last open (DDR_VREF at U1-H6).
unit mm
rule pcb (clearance 0.13 (type via_via via_smd via_pin via_wire))
set edge_clearance 0.5
set max_expansions 6000000
status_file $/board_c_v6.sts
bestsave on $/board_c_v6_best.ses
read session $/board_c_v5.ses
route 3 6
route 3 12
route 3 16
route 2 22
route 2 25
clean 1
miter
write session $/board_c_v6.ses
report status $/board_c_v6_status.txt
quit
