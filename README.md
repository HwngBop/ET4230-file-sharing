# ET4230 — TCP File Sharing: Measurement & Concurrent Tests

Bộ công cụ đo lường và kiểm thử truyền file TCP cho Sprint 1–2: tạo dữ liệu, xác minh SHA-256, đo thời gian, tính throughput Mbps, lưu CSV/metadata và chạy 1/5/10 client đồng thời.

Nhánh **`ha-nguyet`** chứa client, baseline runner, concurrent runner và tài liệu. Server đi kèm nhánh này là bản tuần tự. Để kiểm thử nhiều client, dùng server từ **`cn21-10`** trong một thư mục riêng. Không cần merge các nhánh để chạy thử.

## 1. Điều kiện chạy

- Windows 10/11, Python **3.11.x**; các script cốt lõi chỉ dùng thư viện chuẩn.
- Một máy đủ để chạy thử localhost với 1/5/10 socket độc lập. Kiểm chứng LAN cần hai máy: một máy server, một máy chạy tất cả client.
- Dung lượng trống tối thiểu khoảng 2 GB cho fixture, upload, download; các phiên cũ được giữ lại nên cần thêm dung lượng khi chạy nhiều lần.
- Lệnh Windows bên dưới dùng **Command Prompt (cmd)**, không phải PowerShell. Trong PowerShell, thay `set PYTHONPATH=src` bằng `$env:PYTHONPATH = "src"`.

Kiểm tra Python trong cmd:

```bat
py -3.11 --version
```

Nếu chưa cài, tải Python 3.11 từ [python.org](https://www.python.org/downloads/release/python-3119/), chọn Windows installer phù hợp máy và bật **Add python.exe to PATH**. Mở lại cmd sau khi cài.

Không bắt buộc cài pandas/matplotlib để chạy runner. Có thể cài psutil để metadata Windows lấy thêm RAM/CPU:

```bat
py -3.11 -m pip install psutil==7.1.3
```

Nếu không lấy được thông tin phần cứng, metadata giữ null/unknown. Không tự điền số ước lượng.

## 2. Tải hai thư mục code

### Cách A — Download ZIP, không cần Git

1. Mở [nhánh ha-nguyet](https://github.com/HwngBop/ET4230-file-sharing/tree/ha-nguyet), chọn **Code → Download ZIP** rồi **Extract All**.
2. Mở [nhánh cn21-10](https://github.com/HwngBop/ET4230-file-sharing/tree/cn21-10), tải và giải nén tương tự.
3. Giữ hai thư mục tách biệt. Có thể đổi tên thư mục giải nén thành `runner` và `server` để dễ nhận biết.
4. Trong mỗi thư mục, vào đến nơi thấy `README.md`, `src`, `scripts`, `configs`. Đây là thư mục gốc dùng cho các lệnh tương ứng.

Không copy đè code nhánh server lên nhánh runner. File nguồn của hai thư mục không cần trộn với nhau.

### Cách B — Git

Chạy trong một thư mục làm việc mới:

```bat
git clone --branch ha-nguyet https://github.com/HwngBop/ET4230-file-sharing.git runner
git clone --branch cn21-10 https://github.com/HwngBop/ET4230-file-sharing.git server
```

Nếu cập nhật checkout đã có, kiểm tra `git status` và lưu các thay đổi trước; không dùng lệnh reset/xóa để ép cập nhật. ZIP không có lịch sử Git, vì vậy commit metadata có thể là null; giữ ZIP/revision và source_sha256 cùng kết quả.

## 3. Tạo file thử nghiệm trong thư mục runner

Mở thư mục gốc **runner** bằng File Explorer. Bấm thanh địa chỉ phía trên, nhập `cmd`, nhấn Enter. Cửa sổ cmd mở tại đúng thư mục đó.

Chạy:

```bat
py -3.11 scripts/generate_test_files.py --output-dir test_files/sprint2
```

Kết quả phải có ba file:

| File | Kích thước chính xác |
| --- | ---: |
| test_1MB.bin | 1.000.000 byte |
| test_10MB.bin | 10.000.000 byte |
| test_50MB.bin | 50.000.000 byte |

File có sẵn thì dùng lại. Chỉ thêm `--force` nếu chủ động muốn tạo lại. Generator dùng seed cố định, dữ liệu được ghi theo khối. Giữ cửa sổ này làm **terminal runner**.

## 4. Mở server concurrent trên cùng máy

Mở thư mục gốc **server** bằng File Explorer, nhập `cmd` trên thanh địa chỉ như bước trên. Đây là **terminal server**, độc lập với terminal runner.

Export metadata server trước:

```bat
py -3.11 scripts/collect_environment.py collect --role server --ip 127.0.0.1 --network-type loopback --chunk-size 65536 --output results/s2-server-host.json
```

Sau đó chạy server:

```bat
set PYTHONPATH=src
py -3.11 -m server --host 127.0.0.1 --port 5000 --chunk-size 65536 --max-clients 10 --client-timeout 30
```

Đợi log **LISTENING**. Giữ terminal server mở. Nếu `--max-clients` không được nhận diện, đang dùng nhánh server tuần tự hoặc bản cũ.

Trong File Explorer, copy file **server/results/s2-server-host.json** sang **runner/results/s2-server-host.json**. Chỉ copy file metadata này; nó phải được export từ đúng server. Nếu hai thư mục trên hai máy, cũng chuyển file theo cách tương tự.

## 5. Chạy lần lượt 1, 5, 10 client

Quay lại terminal **runner**. Mỗi lệnh bên dưới phải chạy xong trước khi chạy lệnh kế tiếp.

### 1 client

```bat
py -3.11 scripts/run_concurrent.py --host 127.0.0.1 --port 5000 --num-clients 1 --files-dir test_files/sprint2 --results-dir results/sprint2 --server-metadata results/s2-server-host.json --network-type loopback --download
```

Với ba file và upload/download: **6 dòng CSV**, một client PASS, scenario PASS, mã thoát 0.

### 5 client

```bat
py -3.11 scripts/run_concurrent.py --host 127.0.0.1 --port 5000 --num-clients 5 --files-dir test_files/sprint2 --results-dir results/sprint2 --server-metadata results/s2-server-host.json --network-type loopback --download
```

Kết quả dự kiến: **30 dòng CSV**, năm client PASS và concurrency PASS.

### 10 client

```bat
py -3.11 scripts/run_concurrent.py --host 127.0.0.1 --port 5000 --num-clients 10 --files-dir test_files/sprint2 --results-dir results/sprint2 --server-metadata results/s2-server-host.json --network-type loopback --download
```

Kết quả dự kiến: **60 dòng CSV**, mười client PASS và concurrency PASS nếu server đủ tài nguyên/slot.

Ngay sau mỗi lệnh, kiểm tra mã thoát trong cmd:

```bat
echo %ERRORLEVEL%
```

`0` là PASS, khác 0 là FAIL. Nếu dùng PowerShell, xem `$LASTEXITCODE`. Mỗi lần chạy tạo UUID phiên mới, không ghi đè CSV Sprint 1 hoặc phiên trước. Bỏ `--download` nếu chỉ kiểm tra upload; số dòng khi đó giảm một nửa.

## 6. Mở và đọc kết quả

Terminal in đường dẫn dạng `results/sprint2/<session_id>/`. Mở thư mục đó:

| File/thư mục | Nội dung |
| --- | --- |
| summary.json | PASS/FAIL toàn phiên, từng client, số dòng và bằng chứng overlap |
| all-transfers.csv | CSV tổng hợp sau khi tất cả worker kết thúc |
| environment.json | Máy, Python, commit/source hash, IP, mạng, port, num_clients, chunk |
| runner.log | Tóm tắt kết quả từng client và toàn phiên |
| client-01/transfers.csv | CSV riêng của worker 1; các worker còn lại tương tự |
| client-01/downloads/ | File worker 1 nhận về |

Có thể mở CSV bằng Excel qua **Data → From Text/CSV**, chọn UTF-8 và dấu phẩy. Các cột quan trọng:

- `session_id`: một phiên N client; `client_id`: một worker; `run_id`: một lượt upload/download.
- `num_clients`: số client được cấu hình; socket thực sự mở được xem trong summary.
- `transfer_time_s`, `throughput_mbps`: thời gian và thông lượng ứng dụng.
- `checksum_match=true` và `status=SUCCESS`: đã hoàn tất và xác minh checksum khớp.
- `status=FAILED`: xem `error_message`; throughput phải để trống.
- `environment_id`: tham chiếu environment.json cùng phiên.

Mỗi worker ghi CSV riêng; chỉ thread chính tạo file tổng sau khi worker kết thúc. Console có thể xen dòng giữa các worker, nên dùng CSV/JSON làm nguồn kết quả.

## 7. Cách runner xác nhận concurrency

Mỗi worker có FileClient, socket, filename và thư mục download riêng. Các worker đồng bộ bắt đầu, sau đó **tất cả phải nhận READY cho upload đầu trước khi gửi payload**. Server chỉ phục vụ tuần tự sẽ không vượt được kiểm tra này.

`summary.json` phải có:

- `concurrency.status = PASS`;
- `all_ready_before_payload = true`;
- `shared_payload_completion_overlap_s > 0` với cửa sổ payload/completion của các worker chồng lấn.

Với một client, đây chỉ là kiểm tra cơ sở. Bằng chứng này xác nhận concurrent application dispatch/I/O, không chứng minh CPU thực thi đồng thời hay tốc độ card mạng.

## 8. Công thức và phạm vi phép đo

```text
throughput_mbps = (file_size_bytes × 8) / (transfer_time_s × 1.000.000)
```

- 1 MB = 1.000.000 byte; 1 MiB = 1.048.576 byte.
- Mbps là triệu bit/giây; MB/s là triệu byte/giây. 1 MB/s = 8 Mbps.
- Chunk 64 KiB = 65.536 byte, không phải kích thước mỗi gói TCP.
- Dùng `perf_counter()` từ trước request đến completion, xác minh checksum và rename download; không tính hash nguồn upload trước request hoặc ghi CSV sau đo.
- **Upload đầu có tính thời gian chờ gate READY.** Kết quả dùng để nghiệm thu concurrency; không so trực tiếp như baseline hiệu năng Sprint 1 không có gate.
- Không nhập tay, sửa số liệu hay đổi FAILED thành SUCCESS. `unlimited` nghĩa chương trình không chủ động giới hạn băng thông.

## 9. Chạy giữa hai máy LAN

Chạy server concurrent trên máy server và runner trên máy client. Một máy client có thể tạo đủ 5/10 socket.

1. Trên server, chạy `ipconfig`, lấy IPv4 card mạng đang dùng.
2. Export metadata server bằng IP thật và `--network-type Wi-Fi` hoặc `Ethernet` đúng thực tế.
3. Khởi động server bằng `--host 0.0.0.0`, cùng port/chunk/max-clients như bước 4.
4. Cho phép Python hoặc TCP port 5000 qua firewall mạng riêng khi cần.
5. Copy JSON export server sang runner trên máy client.
6. Chạy runner, thay `127.0.0.1` bằng IP server, thay network-type bằng mạng của client.

Ví dụ **192.168.1.10 chỉ là IP minh họa**:

```bat
py -3.11 scripts/run_concurrent.py --host 192.168.1.10 --port 5000 --num-clients 5 --files-dir test_files/sprint2 --results-dir results/sprint2 --server-metadata results/s2-server-host.json --network-type Wi-Fi --download
```

Client không kết nối đến `0.0.0.0`; localhost chỉ trỏ về chính máy client. Kết quả loopback không thay minh chứng LAN. Giữ CSV, metadata, log server, ảnh terminal và PCAP khi nghiệm thu mạng; video demo theo yêu cầu chung của nhóm.

## 10. Kiểm thử tự động và server revision

Trong terminal runner:

```bat
set PYTHONPATH=src
py -3.11 -m unittest discover -s tests -v
```

Để các test concurrent dùng implementation server từ thư mục server thực tế, đặt thêm biến sau; **thay đường dẫn ví dụ**:

```bat
set CONCURRENT_SERVER_FILE=C:\Projects\server\src\server\server.py
py -3.11 -m unittest discover -s tests -v
set CONCURRENT_SERVER_FILE=
```

Nếu không đặt biến, test dùng fixture threaded riêng; fixture không thay server production. Kết quả kiểm chứng revision hiện tại xem [report/sprint2-verification.md](report/sprint2-verification.md). Chạy trên Linux/Python 3.12 không thay chứng nhận chạy Windows/Python 3.11.

Server `cn21-10` tại `a07b950` đã có nhánh xử lý FILE_BUSY nhưng storage hiện chưa triển khai `try_lock_file`; các test khóa tự cung cấp helper. Vì vậy, không coi test đó là bằng chứng server production đã khóa file trùng tên. Runner dùng tên riêng từng phiên/worker. Client ghi FILE_BUSY là FAILED và giữ kết nối để có thể thử lại.

## 11. Sprint 1 và client tương tác

Server đi kèm `ha-nguyet` vẫn chạy tuần tự, dùng được cho baseline một client. Hướng dẫn đo một client: [report/measurement-guide.md](report/measurement-guide.md).

Chạy client tương tác từ runner:

```bat
py -3.11 src/client/client.py
```

Ví dụ lệnh trong client:

```text
connect 127.0.0.1 5000
upload test_files/sprint2/test_1MB.bin
list
download test_1MB.bin
quit
```

Nếu yêu cầu minh chứng Sprint 1 dùng **10 MiB**, chạy smoke test riêng (khác file baseline 10 MB):

```bat
py -3.11 scripts/smoke_test.py --host 127.0.0.1 --port 5000 --size 10485760
```

Khi nghiệm thu LAN, thay host bằng IP server thật. Smoke test có thể ghi đè file smoke cùng tên; dùng storage thử nghiệm.

## 12. Xử lý lỗi và kết thúc

| Hiện tượng | Kiểm tra |
| --- | --- |
| Không tìm thấy py/Python | Cài Python 3.11 và mở lại cmd |
| Không thấy script | Đứng tại thư mục gốc chứa src/scripts; không ở thư mục cha của ZIP |
| No module named server | Chạy `set PYTHONPATH=src` trong terminal server trước lệnh chạy |
| unrecognized --max-clients | Dùng thư mục server từ cn21-10, không dùng server tuần tự trong runner |
| Connection refused | Server chưa LISTENING, sai IP hoặc port |
| Timeout/concurrency FAIL | Kiểm tra server concurrent, số slot, firewall, tải máy; không chỉ xem CONNECTED |
| SERVER_BUSY | Server hết slot; đóng phiên cũ hoặc kiểm tra --max-clients |
| FILE_BUSY | Ghi nhận FAILED; thử lại sau khi tài nguyên được giải phóng nếu storage có khóa |
| Metadata IP/chunk không khớp | Export lại trên đúng máy server với cấu hình thực tế |
| Checksum mismatch | Giữ CSV lỗi; kiểm tra file nguồn có đổi khi truyền và hai phía đúng code |
| CSV logging failed | Kiểm tra quyền ghi, dung lượng, file đang bị Excel khóa |
| File thử đã tồn tại | Dùng file hiện có hoặc chủ động tạo lại bằng --force |

Sau khi thử xong, Ctrl+C ở terminal server. Runner không tự xóa file đã gửi lên server. Chỉ dọn file có tiền tố `s2_<session_id>_` của phiên đã xác định sau khi lưu chứng cứ; không xóa dữ liệu phiên khác.

## Tài liệu

- [Protocol Sprint 1](report/protocol.md)
- [Measurement và baseline](report/measurement-guide.md)
- [Test plan Sprint 2](report/sprint2-test-plan.md)
- [Kết quả kiểm chứng Sprint 2](report/sprint2-verification.md)
- [Mẫu CSV Sprint 2](results/sprint2-samples/README.md)
