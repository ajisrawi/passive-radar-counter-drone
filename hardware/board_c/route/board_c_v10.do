# Board C v10: v9 with JTAG_TDI, VCCPLL and DDR_A10 ripped up (their vias box in the +1V0 ball U1-G7); G7 fans out first.
unit mm
rule pcb (clearance 0.13 (type via_via via_smd via_pin via_wire))
set edge_clearance 0.5
set max_expansions 6000000
status_file $/board_c_v10.sts
bestsave on $/board_c_v10_best.ses
read session $/board_c_v10_resume.ses
route 3 6
route 3 12
route 3 16
route 2 22
route 2 25
clean 1
miter
write session $/board_c_v10.ses
report status $/board_c_v10_status.txt
quit
