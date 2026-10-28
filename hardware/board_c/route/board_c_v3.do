# OpenRoute run 3 for Board C: weighted A*, soft fanout re-placement, larger search budgets
status_file $/board_c_v3.sts
bestsave on $/board_c_v3_best.ses
fanout
route 5
route 5 6
route 5 11
route 5 16
route 5 21
clean 1
write session $/board_c_v3.ses
report status $/board_c_v3_status.txt
report conflicts $/board_c_v3_drc.txt
quit
