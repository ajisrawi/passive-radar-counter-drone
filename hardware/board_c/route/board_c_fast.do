# OpenRoute fast run (weighted A*) for Board C
status_file $/board_c_fast.sts
bestsave on $/board_c_fast_best.ses
fanout
route 5
route 5 6
route 5 11
route 5 16
route 5 21
clean 1
write session $/board_c_fast.ses
report status $/board_c_fast_status.txt
report conflicts $/board_c_fast_drc.txt
quit
