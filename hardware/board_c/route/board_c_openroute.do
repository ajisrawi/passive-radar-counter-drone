# OpenRoute do-file for Board C (Zynq-7020 carrier, 8 layers / 4 signal)
status_file $/board_c_openroute.sts
bestsave on $/board_c_openroute_best.ses
fanout
route 5
route 5 6
route 5 11
route 5 16
clean 1
write session $/board_c_openroute.ses
report status $/board_c_openroute_status.txt
report conflicts $/board_c_openroute_drc.txt
quit
