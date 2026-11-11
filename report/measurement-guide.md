# Đo lường và CSV — Sprint 1

Bộ công cụ này ghi nhận kết quả của chương trình truyền file client–server. Client là máy chạy lệnh gửi/tải; server là máy lưu file và chờ kết nối. Terminal là cửa sổ nhập lệnh; CSV là bảng văn bản có thể mở bằng Excel; SHA-256 là mã kiểm tra nội dung file.

Luồng: **Tạo file → Truyền file và đo thời gian → Xác minh checksum → Ghi CSV**.

## 1. Các file của phần việc này

| File | Công dụng |
| --- | --- |
| `scripts/generate_test_files.py` | Tạo ba file đúng số byte, không ghi đè nếu chưa dùng `--force` |
| `src/common/measurement.py` | Đồng hồ, UUID, timestamp và công thức Mbps |
| `src/common/csv_logger.py` | Append CSV, kiểm tra schema, ghi header một lần |
| `src/common/environment.py` | Thu thập thông tin máy, lưu metadata theo UUID |
| `scripts/collect_environment.py` | Export từng máy, ghép metadata |
| `scripts/run_baseline.py` | Gọi client hiện có, truyền lần lượt ba file |
| `src/client/client.py` | Tích hợp đo/log cho upload và download, giữ giao thức |
| `tests/test_measurement.py` | Kiểm tra phần mới bằng dữ liệu tạm riêng |
| `results/raw/baseline.csv` | Các lượt đo thật, mỗi lượt một dòng |
| `results/environment.json` | Bộ metadata được tạo gần nhất |
| `results/environments/<environment_id>.json` | Bản lưu metadata tương ứng mỗi phiên, không bị thay khi chạy phiên mới |

Không thay server hay wire protocol. `LIST`/`QUIT` không tạo dòng CSV.

## 2. Chuẩn bị thư mục và Python

Cài Git và Python **3.11.x** theo yêu cầu nhóm. Code cũng đã được kiểm chứng trên Python 3.12.14 trên Linux/container; chưa kiểm chứng bằng Python 3.11 trên Windows. Mở thư mục repo trong VS Code, chọn **Terminal → New Terminal**. Mọi lệnh dưới đây chạy tại thư mục chứa `README.md`, `src/`, `scripts/`.

Nếu đã có repo, dùng `git status` xem có thay đổi chưa lưu trước khi chuyển nhánh; không xóa thay đổi của mình/nhóm.

Windows PowerShell, khi clone mới:

```powershell
git clone --branch ha-nguyet https://github.com/HwngBop/ET4230-file-sharing.git
cd ET4230-file-sharing
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Linux:

```bash
git clone --branch ha-nguyet https://github.com/HwngBop/ET4230-file-sharing.git
cd ET4230-file-sharing
python3.11 -m venv .venv
source .venv/bin/activate
```

Nếu đã có checkout và working tree sạch:

```text
git switch ha-nguyet
```

Sau khi clone, kiểm tra `git branch --show-current` hiển thị `ha-nguyet`. Không ghi đè các thay đổi chưa commit khi cập nhật code.

Phần đo lường chạy bằng thư viện chuẩn, không bắt buộc cài thêm gói. Nếu cần toàn bộ dependencies của nhóm:

```text
python -m pip install -r requirements.txt
```

Nếu PowerShell chặn activate, thay `python` trong các lệnh bằng `.\.venv\Scripts\python.exe`, không cần đổi execution policy. Kiểm tra `python --version`.

## 3. Chạy thử trên một máy bằng hai terminal

### Bước A — tạo file (Windows/Linux cùng lệnh)

```text
python scripts/generate_test_files.py
```

File nằm trong `client_data/uploads/`, lần lượt đúng 1.000.000, 10.000.000, 50.000.000 byte. Muốn chọn thư mục: thêm `--output-dir test_files`. Muốn tạo lại có chủ ý: thêm `--force`. Generator dùng `random.Random(4230 + size_bytes).randbytes()` theo khối cố định 65.536 byte; dùng cùng phiên bản Python, seed và thuật toán để tái lập. Đây là dữ liệu thử, không dùng làm dữ liệu mật mã.

### Bước B — terminal 1: export máy server và chạy server

Export trước khi chạy để terminal không bị chiếm:

```text
python scripts/collect_environment.py collect --role server --ip 127.0.0.1 --network-type loopback --chunk-size 65536 --output results/server-host.json
```

Windows:

```powershell
$env:PYTHONPATH = "src"
python -m server --host 127.0.0.1 --port 5000 --chunk-size 65536
```

Linux:

```bash
PYTHONPATH=src python -m server --host 127.0.0.1 --port 5000 --chunk-size 65536
```

Đợi dòng LISTENING. Giữ terminal này mở.

### Bước C — terminal 2: chạy baseline

Mở terminal mới trong cùng thư mục repo, chọn cùng Python/venv. Windows/Linux cùng lệnh:

```text
python scripts/run_baseline.py --host 127.0.0.1 --port 5000 --network-type loopback --server-metadata results/server-host.json --download
```

Chạy 3 upload + 3 download. Bỏ `--download` nếu chỉ cần 3 upload. Script kiểm tra file đủ kích thước và server metadata có chunk 65536; metadata phải phản ánh đúng lệnh server đang chạy. Một kết nối duy nhất, các lượt tuần tự, không tự giới hạn băng thông.

Các tùy chọn thêm:

```text
--files-dir test_files
--csv results/raw/my-baseline.csv
--results-dir results
```

`--csv` chỉ đổi vị trí CSV; metadata vẫn ở `--results-dir`. Giữ cả CSV và thư mục metadata khi chia sẻ kết quả. File download nằm trong `client_data/downloads/`.

Script trả exit code 0 nếu toàn bộ thành công, khác 0 nếu có lỗi. PowerShell kiểm tra `$LASTEXITCODE`; Linux kiểm tra `echo $?` ngay sau lệnh. Tắt server bằng Ctrl+C ở terminal 1 sau khi xong.

## 4. Chạy trên hai máy thật

Cả hai máy cần cùng phiên bản code. Nối cùng LAN/Wi-Fi. Dưới đây **192.168.1.10 là IP ví dụ của server, phải thay bằng IP thật**. Windows xem bằng `ipconfig`, Linux bằng `ip addr`. Chọn IPv4 của card mạng đang dùng, không chọn 127.0.0.1.

Trên máy server, export (thay `Wi-Fi` bằng `Ethernet` nếu đang dùng cáp):

```text
python scripts/collect_environment.py collect --role server --ip 192.168.1.10 --network-type Wi-Fi --chunk-size 65536 --output results/server-host.json
```

Chạy server trên Windows:

```powershell
$env:PYTHONPATH = "src"
python -m server --host 0.0.0.0 --port 5000 --chunk-size 65536
```

Linux:

```bash
PYTHONPATH=src python -m server --host 0.0.0.0 --port 5000 --chunk-size 65536
```

`0.0.0.0` dùng để server lắng nghe các interface. Client phải kết nối IP thật, không dùng 0.0.0.0. Cho phép ứng dụng/port TCP 5000 trong firewall mạng riêng khi cần.

Copy file `results/server-host.json` từ máy server sang thư mục `results/` của máy client, không tạo lại file server trên client.

Trên client, tạo test files rồi chạy:

```text
python scripts/generate_test_files.py
python scripts/run_baseline.py --host 192.168.1.10 --port 5000 --network-type Wi-Fi --server-metadata results/server-host.json --csv results/raw/lan-baseline.csv --download
```

Nếu file thử đã có, bỏ lệnh tạo. `--network-type` ở runner mô tả kết nối của **client**; mạng của server lấy từ file export. Chỉ khai báo theo thực tế. IP client/server thực tế lấy từ socket; file server được kiểm tra role, chunk và IP.

Runner tự thu thập client và ghép server thành `environment.json` cùng bản lưu theo UUID. Việc export không xác minh từ xa OS/hardware: người chạy cần đảm bảo file export được lấy từ đúng server và cấu hình không đổi.

### Export/ghép thủ công cho client tương tác

Ví dụ client có IP **192.168.1.20** (cũng phải thay):

```text
python scripts/collect_environment.py collect --role client --ip 192.168.1.20 --network-type Wi-Fi --chunk-size 65536 --output results/client-host.json
python scripts/collect_environment.py merge --client results/client-host.json --server results/server-host.json --port 5000
python src/client/client.py --environment results/environment.json --csv results/raw/manual.csv
```

Trong client:

```text
connect 192.168.1.10 5000
upload test_1MB.bin
download test_1MB.bin
list
quit
```

Nếu chạy client tương tác không truyền `--environment`, client tự tạo metadata máy mình và đánh dấu thông tin server/mạng chưa xác định là unknown. Muốn đủ metadata để nộp, dùng runner hoặc ghép metadata như trên. Khi dùng file ghép thủ công, tự kiểm tra IP/port và môi trường đó khớp kết nối.

## 5. Phương pháp đo và công thức

`perf_counter()` là đồng hồ đo khoảng thời gian chính xác, không phải ngày giờ. `transfer_start` và `transfer_end` giữ trong đối tượng Measurement; CSV lưu hiệu `transfer_time_s`. Timestamp riêng là UTC ISO 8601 có `+00:00`; giờ Việt Nam bằng UTC + 7.

Bắt đầu ngay trước request; kết thúc sau completion, xác minh checksum và (download) đổi `.part` thành file đích. Bao gồm trao đổi header, truyền payload, đọc/ghi file, hash streaming và xử lý completion. Không tính hash nguồn upload trước request, mở kết nối, thu thập metadata, ghi CSV hay in kết quả sau đo. Không gọi fsync nên không đo thời gian đảm bảo dữ liệu đã xuống thiết bị lưu trữ vật lý. Màn hình và CSV dùng cùng thời lượng chưa làm tròn; màn hình chỉ định dạng ít chữ số hơn.

```text
throughput_mbps = file_size_bytes × 8 / (transfer_time_s × 1_000_000)
```

Ví dụ **chỉ minh họa công thức**: 10.000.000 byte / 2 giây → 40 Mbps. Không đưa ví dụ này vào baseline.

- Mbps: triệu bit/giây. MB/s: triệu byte/giây. 1 MB/s = 8 Mbps.
- 1 MB = 1.000.000 byte. 1 MiB = 1.048.576 byte.
- Chunk 64 KiB = 65.536 byte, là khối xử lý chương trình, không phải kích thước mỗi gói TCP.
- Throughput là tốc độ ứng dụng theo phạm vi đo, không phải tốc độ vật lý của card mạng.
- unlimited: chương trình không áp dụng giới hạn băng thông; mạng vẫn có giới hạn thực tế.

Checksum upload: hash file nguồn so với SHA-256 server tính khi nhận/ghi. Download: SHA-256 streaming trên byte đã ghi vào file tạm so với hash server trả về. Không đọc lại toàn bộ đĩa sau ghi, không chứng minh độ bền lưu trữ vật lý. Chỉ công bố SUCCESS khi đủ byte, completion hợp lệ và checksum khớp.

## 6. Cách đọc CSV

Mở bằng Excel → Data → From Text/CSV → chọn UTF-8 và dấu phẩy, hoặc mở file trong VS Code. Mỗi lần thử upload/download có một dòng kể cả lỗi tiền xử lý có thể ghi được; lỗi kết nối của runner trước khi bắt đầu transfer được báo terminal, chưa có dòng transfer.

| Cột | Ý nghĩa |
| --- | --- |
| run_id | UUID phân biệt từng lượt |
| timestamp | Ngày giờ bắt đầu đo; nếu chưa bắt đầu, ngày giờ tạo lượt thử |
| direction | upload/download |
| file_name | Tên file |
| file_size_bytes | Kích thước byte xác định được; chưa biết thì trống |
| chunk_size_bytes | Buffer thực tế phía client; buffer server nằm trong metadata |
| num_clients | 1 trong runner tuần tự |
| bandwidth_limit_mbps | unlimited |
| transfer_time_s | Giây đến khi hoàn tất hoặc lỗi; chưa bắt đầu thì trống |
| throughput_mbps | Chỉ có với SUCCESS và thời gian hợp lệ |
| checksum_match | true: đã khớp; false: xác định mismatch; trống: chưa xác minh được |
| status | SUCCESS/FAILED |
| environment_id | Tra file results/environments/<id>.json |
| error_message | Lý do thất bại nếu có |

Header không lặp khi append. Nếu schema cũ khác, chọn CSV mới, không xóa dữ liệu để cố ghép. Logger dành cho Sprint 1 một writer, chưa hỗ trợ nhiều tiến trình ghi cùng file. Lỗi ghi đĩa/schema được báo `CSV LOGGING FAILED`, không thể đảm bảo có dòng CSV nếu chính thao tác ghi bị lỗi.

Metadata giữ OS, Python, CPU, số lõi, RAM mà OS nhìn thấy (có thể là VM/container), IP, mạng, port, cấu hình và commit SHA. `working_tree_dirty=true` nghĩa code có thay đổi chưa commit; phải giữ phiên bản code tương ứng cùng kết quả, commit SHA riêng chưa đủ tái tạo các thay đổi đó. Phần cứng/mạng không đọc được ghi null/unknown, không đoán.

## 7. Kiểm thử và nghiệm thu

Windows:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

Linux:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Có thể dùng `python -m pytest -q` sau khi cài pytest. Test tạo dữ liệu tạm, không ghi vào baseline thật. Kiểm tra bằng test đầy đủ và chạy baseline:

- [ ] Generator in đúng 1.000.000, 10.000.000, 50.000.000 byte.
- [ ] CSV có đủ 3 kích thước, UUID khác nhau, thời lượng dương.
- [ ] Throughput tính lại bằng công thức khớp số CSV.
- [ ] SUCCESS đi kèm checksum_match=true.
- [ ] Lỗi/mismatch ghi FAILED, throughput trống.
- [ ] environment_id trỏ đến metadata lưu được.
- [ ] Điều kiện 1 client, chunk 65536, unlimited đúng thực tế.
- [ ] Có code và lệnh tái lập; không nhập tay số benchmark.
- [ ] Nếu nộp minh chứng LAN, đã chạy lại trên hai máy thật.

Đã kiểm chứng logic qua 6 lượt truyền loopback thành công và 44 kiểm thử tự động. CSV, metadata và log của lần đo loopback nằm trong `results/`; xem `results/verification.md`. Chạy các lệnh trên để tạo kết quả tại môi trường thực tế. Loopback chưa thay demo hai máy theo protocol của nhóm. Sprint 1 chưa cần plot, mean/std, 5 repetitions hay multi-client.

## 8. Lỗi thường gặp

| Lỗi | Cách kiểm tra |
| --- | --- |
| Connection refused | Server chưa chạy, sai port/IP; xem LISTENING và dùng port giống nhau |
| Timeout | Kiểm tra server, cùng mạng, firewall và kết nối; server tuần tự nên đóng client cũ trước |
| Sai IP | Lấy IPv4 LAN của server; localhost chỉ trỏ chính máy đang chạy client |
| File không tồn tại | Chạy generator, kiểm tra --files-dir; file tên khác không thuộc baseline mặc định |
| File đã tồn tại | Dùng file hiện có hoặc chạy generator --force nếu muốn tạo lại |
| No module named common/server | Đứng đúng thư mục gốc, đặt PYTHONPATH=src theo lệnh cho hệ điều hành |
| Checksum mismatch | Giữ dòng FAILED; kiểm tra file có đổi khi truyền, hai máy cùng code, không sửa checksum thành true |
| CSV schema mismatch | Chọn --csv với tên mới; giữ CSV cũ |
| CSV LOGGING FAILED | Kiểm tra quyền ghi, dung lượng và Excel có đang khóa file không |
| Server metadata IP/chunk không khớp | Export lại trên đúng máy server theo cấu hình đang chạy |
| Port đang được dùng | Dừng server cũ do mình chạy hoặc chọn port khác ở cả server/client và metadata |

## 9. Kịch bản demo và lời trình bày

1. Mở file nhiệm vụ và chỉ ra các script/helper mình phụ trách.
2. Chạy generator, chỉ ba kích thước byte.
3. Chạy server ở terminal 1, baseline ở terminal 2.
4. Chỉ SHA-256 MATCH và run_id trên màn hình.
5. Mở CSV, chỉ 3 hoặc 6 dòng mới, UUID, time, Mbps, checksum, SUCCESS.
6. Mở metadata đúng UUID; giải thích loopback hay hai máy thực tế.
7. Khi cần minh họa FAILED, dùng client tương tác tải file chắc chắn không tồn tại vào CSV demo riêng, giữ baseline thành công gốc.

Có thể trình bày: “Em bổ sung công cụ tạo dữ liệu, đo và lưu kết quả cho chương trình truyền file của nhóm. Mỗi lần truyền có UUID và thông tin môi trường. Em dùng perf_counter đo từ trước request đến khi nhận completion và kiểm tra checksum xong. Tốc độ tính bằng số byte nhân 8 chia thời gian và một triệu, đơn vị Mbps. CSV được ghi tự động, giữ cả lỗi. Baseline hiện tại dùng một client và buffer 64 KiB. Nếu chạy localhost, em ghi rõ đó là loopback và cần đo lại trên hai máy để đánh giá mạng LAN.”
