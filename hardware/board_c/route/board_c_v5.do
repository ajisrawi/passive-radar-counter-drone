# Board C v5: finish v4 with the fixed router (plane fanouts keep their stacked microvias; clean no longer orphans
# connections that ride on rerouted copper). Resumes v4's final copper.
unit mm
rule pcb (clearance 0.13 (type via_via via_smd via_pin via_wire))
set edge_clearance 0.5
set max_expansions 6000000
status_file $/board_c_v5.sts
bestsave on $/board_c_v5_best.ses
read session $/board_c_v4.ses
route 3 8
route 3 12
route 3 16
route 2 22
route 2 25
clean 1
miter
write session $/board_c_v5.ses
report status $/board_c_v5_status.txt
quit
