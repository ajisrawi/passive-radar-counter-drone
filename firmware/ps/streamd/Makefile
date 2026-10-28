# Build on the board (ADI Kuiper Linux ships gcc): make && sudo ./pcl_streamd --host <gpu host> --port 50001
CFLAGS ?= -O2 -Wall -Wextra -march=armv7-a -mfpu=neon -mfloat-abi=hard
pcl_streamd: pcl_streamd.c
	$(CC) $(CFLAGS) -o $@ $<
clean:
	rm -f pcl_streamd
