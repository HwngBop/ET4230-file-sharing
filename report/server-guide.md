# Hướng dẫn TCP Server — Sprint 1

## Cấu trúc và phạm vi

Code tuân theo cấu trúc trong README:

- `src/server/server.py`: TCP server tuần tự và xử lý command.
- `src/server/config.py`: đọc, kiểm tra cấu hình và ghi đè bằng CLI.
- `src/server/storage.py`: kiểm tra filename, quản lý file tạm và file đích.
- `src/server/logging_config.py`: logging JSON Lines.
- `src/server/storage/`: file chia sẻ, có staging `.uploads/`.
- `src/common/protocol.py`: framing dùng chung cho client/server.
- `src/client/`: dành cho phần triển khai client.
- `configs/server.json`: cấu hình server mặc định.
- `tests/test_server.py`: kiểm thử unit và TCP integration bằng pytest.
- `scripts/smoke_test.py`: kiểm tra upload, list, download, quit qua localhost/LAN.
- `results/`, `plots/`, `demo/`: dành cho kết quả benchmark, biểu đồ và demo sau này.
- `report/protocol.md`: đặc tả application protocol.

Sprint 1 tập trung vào tính đúng: server phục vụ một client tại một thời điểm.
Client hiện tại cần đóng kết nối, gửi `QUIT` hoặc hết timeout để server xử lý
client tiếp theo. Multi-client, SHA-256 trong protocol, benchmark, tài khoản,
authentication, resume và TLS chưa thuộc phần triển khai Sprint 1.

## Cài đặt

Python mục tiêu **3.11.x**, được ghi trong `.python-version`. Code tương thích
Python 3.11 trở lên. Giữ nguyên dependency của `requirements.txt`;
`pyproject.toml` cũng lấy dependency từ file này.

Chạy từ thư mục gốc repository. Trên Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
```

Trên Linux/macOS:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e . --no-deps
```

Cài editable (`-e .`) giúp Python tìm thấy package trong `src/`. Server chỉ dùng
thư viện chuẩn; pytest phục vụ kiểm thử, còn pandas, matplotlib và psutil dành
cho benchmark và báo cáo của dự án.

Các lệnh tiếp theo dùng `python` của môi trường ảo. Trên Windows có thể dùng
`.\.venv\Scripts\python.exe`, trên Linux/macOS dùng `.venv/bin/python`.

## Chạy server

```bash
python -m server --host 0.0.0.0 --port 5000
```

Entry point nằm trong `src/server/`, không thêm file code ở thư mục gốc.
Có thể dùng `python -m server.server` với cùng tham số.

```bash
python -m server --config configs/server.json --storage-dir ./shared --client-timeout 60
python -m server --help
```

| Setting / CLI | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `host` / `--host` | `0.0.0.0` | Mọi IPv4 interface |
| `port` / `--port` | `5000` | TCP port; `0` để hệ điều hành chọn port khi test |
| `storage_dir` / `--storage-dir` | `src/server/storage/` | Thư mục file chia sẻ |
| `log_file` / `--log-file` | `logs/server.log` | File log JSON Lines |
| `chunk_size` / `--chunk-size` | `65536` | Kích thước chunk theo byte |
| `client_timeout` / `--client-timeout` | `30` | Timeout socket khi không tiến triển, tính bằng giây |
| `max_file_size` / `--max-file-size` | `1073741824` | Upload tối đa 1 GiB |

Mặc định đọc `configs/server.json`. Tham số CLI được ưu tiên hơn JSON. Đường dẫn
tương đối trong JSON tính từ thư mục chứa JSON; đường dẫn CLI tính từ thư mục
làm việc hiện tại. Server tự tạo storage, staging và thư mục log. `Ctrl+C` đóng
socket và dừng server.

Upload ghi vào `.uploads/`, kiểm tra đủ số byte, đóng file tạm rồi dùng atomic
replace để lưu file đích. Upload thành công ghi đè file cùng tên. Ngắt giữa chừng
hoặc timeout sẽ xóa file tạm của lượt truyền và giữ file đích cũ. Nếu tiến trình
bị kill hoặc máy mất điện, có thể còn `.part` trong staging; `LIST` không liệt kê chúng.

## Protocol và kiểm tra LAN/Wi-Fi

Đọc [protocol.md](protocol.md) để triển khai client tương thích. Header là JSON
kết thúc bằng LF; payload file được đọc theo đúng `file_size`, không dựa vào
ranh giới mỗi lần `recv()` hay ký tự xuống dòng trong file.

1. Chạy server với `--host 0.0.0.0 --port 5000`.
2. Lấy IPv4 LAN của máy server bằng `ipconfig` trên Windows hoặc `ip addr` trên Linux.
3. Cho phép Python/TCP port 5000 qua firewall trên mạng đang dùng.
4. Trên máy cùng LAN/Wi-Fi có source của dự án, chạy bằng IP thực của server:

```bash
python scripts/smoke_test.py --host 192.168.1.20 --port 5000
```

Kiểm tra trên cùng máy:

```bash
python scripts/smoke_test.py --host 127.0.0.1 --port 5000
```

Script upload dữ liệu nhị phân, kiểm tra `LIST`, download và so sánh toàn bộ byte,
sau đó gửi `QUIT`. Mặc định tạo/ghi đè và giữ lại `sprint1-smoke.bin` trên server;
có thể đổi bằng `--filename` và `--size` (byte). Script này chỉ cần thư viện chuẩn.
Client phải dùng IP LAN thực, không kết nối đến địa chỉ bind `0.0.0.0`.

## Logging

Log ghi ra terminal và `logs/server.log`. Mỗi dòng JSON có `timestamp` kèm múi giờ,
`client_ip`, `client_port`, `command`, `filename`, `file_size`, `status`, `message`.
Transfer có thêm `transferred_bytes`; trường không áp dụng là `null`.
Log tự xoay ở 5 MiB, giữ hai bản cũ.

```json
{"timestamp":"2026-11-02T17:00:00+07:00","client_ip":"192.168.1.20","client_port":53000,"command":"UPLOAD","filename":"sample.bin","file_size":1024,"status":"SUCCESS","transferred_bytes":1024,"message":"UPLOAD completed"}
```

## Kiểm thử

```bash
python -m pytest
```

Test dùng loopback TCP thật với port do hệ điều hành chọn và storage tạm, bao gồm
file nhị phân, file rỗng, ghi đè, các command, `FILE_NOT_FOUND`, input không hợp lệ,
TCP fragmentation, frame gộp, ngắt giữa chừng, timeout, lỗi ghi file và log.
Thread chỉ dùng trong test để điều khiển server; server vẫn xử lý tuần tự.
Kết nối giữa hai máy cần xác nhận thực tế theo hướng dẫn LAN ở trên.
