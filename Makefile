# F.CSM302 БД1 — IV-2-9 Designing a Thread Pool
CC      ?= gcc
CFLAGS  ?= -std=c11 -Wall -Wextra -O2 -g
LDLIBS  += -pthread
BUILD   := build

.PHONY: all run client test tsan ui clean

all: $(BUILD)/threadpool_sim $(BUILD)/client

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/threadpool_sim: src/main.c src/threadpool.c src/threadpool.h | $(BUILD)
	$(CC) $(CFLAGS) -o $@ src/main.c src/threadpool.c $(LDLIBS)

$(BUILD)/client: examples/client.c src/threadpool.c src/threadpool.h | $(BUILD)
	$(CC) $(CFLAGS) -o $@ examples/client.c src/threadpool.c $(LDLIBS)

# Өгөгдмөл параметрээр нэг удаа ажиллуулж trace гаргана
run: $(BUILD)/threadpool_sim
	./$(BUILD)/threadpool_sim -w 3 -q 5 -n 15 -o $(BUILD)/trace.json

client: $(BUILD)/client
	./$(BUILD)/client

# Бүх үндсэн + boundary/error тест
test: all
	sh tests/run_tests.sh

# ThreadSanitizer-ээр race condition шалгах
tsan: | $(BUILD)
	$(CC) -std=c11 -g -O1 -fsanitize=thread -o $(BUILD)/threadpool_tsan src/main.c src/threadpool.c $(LDLIBS)
	./$(BUILD)/threadpool_tsan -w 4 -q 3 -n 40 -d 5-30 -a 0-5 -p retry -r 2

# Interactive UI (http://localhost:8000)
ui: $(BUILD)/threadpool_sim
	python3 tools/server.py

clean:
	rm -rf $(BUILD)
