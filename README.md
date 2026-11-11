# ET4230 — TCP Client–Server File Sharing

**Học phần:** ET4230 — Mạng máy tính  
**Đề 13:** Chia sẻ tệp Client–Server: tin cậy và tính toàn vẹn  
**Ngôn ngữ:** Python 3.11.x  
**Trạng thái:** Sprint 1 — MVP (Server tuần tự, chưa hỗ trợ client đồng thời)

## 1. Mục tiêu và phạm vi

Hệ thống truyền tệp qua TCP socket, có các lệnh `UPLOAD`, `DOWNLOAD`, `LIST`, `QUIT` và đọc/ghi dữ liệu nhị phân theo từng chunk. Phiên bản chỉnh sửa bổ sung SHA-256 end-to-end và kiểm tra file tạm trước khi commit.

| Chức năng | Sprint 1 |
| --- | --- |
| Upload / download / list | Đã có trong source, cần demo hai máy |
| TCP application framing | JSON UTF-8 + `\n`; payload theo `file_size` |
| Chunked file transfer | 64 KiB mặc định |
| SHA-256 upload/download | Đã bổ sung trong bản sửa, cần nhóm kiểm tra khi tích hợp |
| CSV logger + benchmark | Chưa có trong bản sửa (Member 5) |
| Multi-client đồng thời | Sprint 2 |
| Resume / GUI / TLS | Ngoài phạm vi Sprint 1 |

**Lưu ý:** SHA-256 kiểm tra toàn vẹn dữ liệu, **không phải mã hóa**, không tạo quyền truy cập hay xác thực người gửi. Không truyền dữ liệu nhạy cảm qua mạng chưa tin cậy.

## 2. Cấu trúc repo hiện tại

```text
ET4230-file-sharing/
├── configs/server.json
├── report/protocol.md
├── report/server-guide.md
├── report/client-guide.md
├── scripts/smoke_test.py
├── src/
│   ├── common/protocol.py
│   ├── client/client.py
│   └── server/
│       ├── __main__.py
│       ├── config.py
│       ├── logging_config.py
│       ├── server.py
│       └── storage.py
├── tests/test_server.py
├── tests/test_integrity.py       # mới bổ sung trong bản review
├── requirements.txt
└── README.md
```

`src/server/storage/`, `logs/`, `client_data/uploads/`, `client_data/downloads/` được tạo khi chạy hoặc lúc setup; không commit các tệp runtime hay tệp test lớn. Các thư mục `results/`, `plots/`, `demo/` cần bổ sung khi nhóm xây dựng benchmark và thu thập minh chứng.

## 3. Yêu cầu môi trường

- Python **3.11.x** (cài riêng trước, không đặt `python==3.11` trong `requirements.txt`).
- Windows 10/11 hoặc Linux; TCP socket hoạt động qua LAN/Wi-Fi.
- Server/Client core chỉ dùng Python standard library.
- `pytest`, `pandas`, `matplotlib`, `psutil` trong `requirements.txt` dùng cho kiểm thử và các Sprint tiếp theo.

### Cài đặt Windows PowerShell

```powershell
git clone https://github.com/HwngBop/ET4230-file-sharing.git
cd ET4230-file-sharing
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python --version
```

Nếu PowerShell không cho chạy activation script, có thể dùng `.\.venv\Scripts\python.exe` trực tiếp thay cho `python` (không cần đổi execution policy).

### Linux/macOS

```bash
git clone https://github.com/HwngBop/ET4230-file-sharing.git
cd ET4230-file-sharing
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python --version
```

## 4. Chạy TCP Server

**Chạy từ thư mục gốc repo.** Project hiện chưa có `pyproject.toml` nên cần chỉ đường dẫn `src/` khi chạy module server.

**Windows PowerShell:**

```powershell
$env:PYTHONPATH = "src"
python -m server --host 0.0.0.0 --port 5000
```

**Linux/macOS:**

```bash
PYTHONPATH=src python -m server --host 0.0.0.0 --port 5000
```

Có thể tùy chỉnh:

```text
--config configs/server.json
--host 0.0.0.0
--port 5000
--storage-dir <path>
--chunk-size 65536
--client-timeout 30
--max-file-size 1073741824
```

Máy server thường dùng `0.0.0.0` để lắng nghe tất cả IPv4 interface. Địa chỉ **client phải kết nối** là IPv4 LAN thực của server, ví dụ `192.168.1.10`, không phải `0.0.0.0`.

## 5. Chạy TCP Client

Trong terminal khác tại thư mục gốc repo:

```powershell
python src/client/client.py
```

Ví dụ một phiên dùng:

```text
> connect 192.168.1.10 5000
> upload "C:\Users\me\Desktop\test.pdf"
> list
> download test.pdf
> quit
```

Client tìm tệp upload theo đường dẫn nhập hoặc trong `client_data/uploads/`. Tệp tải về nằm trong `client_data/downloads/`. Khi hoàn thành, Client hiển thị **SHA-256 MATCH**, transfer time và application throughput bằng **Mbps**.

**Khuyến nghị:** chạy Client và Server ở **hai laptop/host khác nhau**, cùng mạng LAN/Wi-Fi; mở TCP port 5000 trên firewall của máy Server nếu cần. Không dùng localhost làm minh chứng mạng hai máy.

## 6. Protocol tầng ứng dụng

**Đặc tả chính:** [report/protocol.md](report/protocol.md)

Một header: JSON UTF-8 trên **một dòng**, kết thúc bằng byte LF (`0A`), tối đa **65.536 byte** bao gồm LF. Khi có payload, nhận **đúng `file_size` byte** bằng các lần `recv` (không giả định một `send` tương ứng một `recv`).

```text
[JSON header][LF][file_size binary bytes][next JSON header][LF]...
```

UPLOAD: `UPLOAD + filename + file_size + sha256` → `READY` → file bytes → `SUCCESS + sha256` (hoặc `ERROR`).

DOWNLOAD: `DOWNLOAD + filename` → `OK + file_size` → file bytes → `SUCCESS + sha256`. Client kiểm tra checksum trước khi đổi `.part` thành file đích.

## 7. Kiểm thử tự động

Cài dependencies xong, chạy từ gốc repo:

**Windows:**

```powershell
$env:PYTHONPATH = "src"
python -m pytest -q
```

**Linux/macOS:**

```bash
PYTHONPATH=src python -m pytest -q
```

Có thể chạy riêng bài test checksum:

```powershell
python -m unittest discover -s tests -p "test_integrity.py" -v
```

Test thực tế với Server đang chạy (mặc định 10 MiB):

```bash
python scripts/smoke_test.py --host 192.168.1.10 --port 5000 --size 10485760
```

Kết quả kỳ vọng gồm `UPLOAD OK`, `LIST OK`, `DOWNLOAD OK`, `SHA-256 MATCH`, `QUIT OK`. Ghi lại kết quả màn hình, log server và Wireshark `.pcapng` khi chạy hai máy thật.

<CodeBlock language="markdown" editable>
## 8. Phương pháp đo hiệu năng


Định nghĩa của nhóm cho application throughput:

$$
\mathrm{Throughput}\;(\mathrm{Mbps}) =
\frac{8 \times \mathrm{FileSizeBytes}}
{10^{6} \times \mathrm{TransferTimeSeconds}}
$$

Trong đó:
- file_size_bytes: Kích thước tệp truyền, tính bằng byte.
- transfer_time_s: Thời gian hoàn tất quá trình truyền, tính bằng giây.
- Throughput (Mbps): Thông lượng ở tầng ứng dụng, tính bằng megabit/giây.
Phương pháp đo
Thời gian đo phía Client được tính từ lúc bắt đầu gửi request đến khi nhận completion response và hoàn tất xác minh checksum.

Đối với upload, không tính thời gian tính SHA-256 của file nguồn trước khi bắt đầu truyền.

Đây là application throughput, không phải tốc độ đường truyền vật lý hay bit rate trên wire.

## 9. Log, kết quả, minh chứng

- Server ghi log JSON Lines tại `logs/server.log` (có `timestamp`, `client_ip`, `command`, `filename`, `file_size`, `status`, `transferred_bytes` khi có).
- Lưu CSV thực nghiệm từ Member 5 vào `results/raw/`, script tạo biểu đồ vào `scripts/`, ảnh vào `plots/`.
- Lưu minh chứng demo vào `demo/`: ảnh terminal hai máy, Wireshark PCAP, video 3–5 phút khi hoàn thành.
- Không sửa tay số liệu để làm đẹp biểu đồ; giữ cả raw CSV và phương pháp tính.

