# Board C v7: v6 with the +1V0 fanout at U1-G7 (offset microvia/buried via) removed and redone.
unit mm
rule pcb (clearance 0.13 (type via_via via_smd via_pin via_wire))
set edge_clearance 0.5
set max_expansions 6000000
status_file $/board_c_v7.sts
bestsave on $/board_c_v7_best.ses
read session $/board_c_v7_resume.ses
route 3 6
route 3 12
route 3 16
route 2 22
route 2 25
clean 1
miter
write session $/board_c_v7.ses
report status $/board_c_v7_status.txt
quit
