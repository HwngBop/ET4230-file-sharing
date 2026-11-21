# Sprint 2 — Multi-client runner, CSV và môi trường đo

## 1. Phạm vi và phụ thuộc

Runner `scripts/run_concurrent.py` tạo 1, 5 hoặc 10 worker trên một laptop; mỗi worker mở một TCP connection đến server. Không cần 5/10 máy vật lý. Để đo LAN cần ít nhất một máy client và một máy server; chạy localhost chỉ là kiểm chứng loopback.

**Phụ thuộc server:** bản `main` tại `b2e3c98` vẫn phục vụ tuần tự. Server concurrent đã có trên nhánh `cn21-10`, commit `a07b950`. Runner không tự đổi server, merge branch hay sửa `main`. Chuẩn bị server bằng nhánh concurrent đã được nhóm review. S2-01/S2-02/S2-03/S2-04 cần nhóm đối chiếu trạng thái trên bảng công việc; trong repo hiện tại đã kiểm chứng được giao thức READY/SUCCESS, SHA-256 và server `cn21-10`.

Các thay đổi:

- `scripts/run_concurrent.py`: worker, đồng bộ, kiểm chứng overlap, kết quả tổng hợp.
- `src/client/client.py`: thêm cấu hình tùy chọn `num_clients`, `client_id`, `session_id`, schema CSV và timeout. Giá trị mặc định giữ cách chạy Sprint 1.
- `src/common/measurement.py`: truyền số client và định danh thực tế vào từng phép đo.
- `src/common/csv_logger.py`: schema Sprint 2 tùy chọn; schema mặc định Sprint 1 giữ nguyên.
- `tests/test_concurrent_runner.py`: các ca chấp nhận, lỗi và server tuần tự.
- `results/sprint2-samples/`: mẫu từ chạy thật loopback, không chứa địa chỉ LAN, hostname, CPU hay RAM cụ thể.

Hướng dẫn cmd Windows từng bước nằm trong [README.md](../README.md). Client/runner dùng nhánh `ha-nguyet`; server dùng thư mục riêng từ `cn21-10`.

## 2. Chuẩn bị file

Dùng Python 3.11.x theo nhóm; phần này chỉ dùng thư viện chuẩn. Đứng tại thư mục chứa README/src/scripts. Bộ test và các mẫu hiện tại chạy trên Python 3.12.14 Linux; chưa chứng nhận riêng Windows/Python 3.11.

Tạo fixture riêng Sprint 2, giữ nguyên file và CSV Sprint 1:

```text
python scripts/generate_test_files.py --output-dir test_files/sprint2
```

Nếu file đã tồn tại, dùng lại file đó; chỉ thêm `--force` khi chủ động muốn tạo lại. Runner đọc tất cả file `*.bin` trực tiếp trong thư mục, yêu cầu không rỗng và tên tối đa 180 byte UTF-8. Mặc định ba file 1/10/50 MB theo hệ thập phân. Không sửa file nguồn trong khi chạy. Mỗi worker dùng hard link đến dữ liệu nguồn để giảm dung lượng; nếu filesystem không hỗ trợ thì copy. Hard link chỉ đổi tên đường dẫn, không nhân bản dữ liệu; worker không chỉnh nội dung nguồn.

## 3. Chuẩn bị server

Cửa sổ terminal server phải đứng trong checkout của nhánh concurrent. Không chuyển nhánh khi working tree có thay đổi chưa lưu. Có thể dùng hai thư mục repo riêng cho server và runner.

Nếu đã có checkout sạch của server:

```text
git fetch origin
git switch cn21-10
```

Trên server, export thông tin **từ đúng máy đang chạy server**, chọn IP/mạng thực tế. Với localhost:

```text
python scripts/collect_environment.py collect --role server --ip 127.0.0.1 --network-type loopback --chunk-size 65536 --output results/s2-server-host.json
```

Công cụ collector hiện ghi hardware/commit/mạng/chunk; `max_clients` là cấu hình server cần ghi bổ sung trong ghi chú thí nghiệm (mặc định lệnh dưới là 10). Metadata export không phải kiểm tra cấu hình từ xa, phải đúng máy và đúng revision đang chạy.

Windows PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m server --host 0.0.0.0 --port 5000 --chunk-size 65536 --max-clients 10 --client-timeout 30
```

Linux:

```bash
PYTHONPATH=src python -m server --host 0.0.0.0 --port 5000 --chunk-size 65536 --max-clients 10 --client-timeout 30
```

Đợi LISTENING. Nếu báo không có tùy chọn `--max-clients`, đang chạy server tuần tự/cũ. `0.0.0.0` là địa chỉ lắng nghe; client dùng IP LAN thật của server, hoặc 127.0.0.1 khi cùng máy. Đóng các kết nối cũ để đủ chỗ cho cả 10 worker.

## 4. Chạy runner — ba cấu hình

Trong terminal khác, đứng tại checkout chứa `scripts/run_concurrent.py`. Windows có thể dùng `py -3.11` thay `python`; Linux dùng Python/venv đã chọn.

```text
python scripts/run_concurrent.py --host 127.0.0.1 --port 5000 --num-clients 1 --files-dir test_files/sprint2 --results-dir results/sprint2 --server-metadata results/s2-server-host.json --network-type loopback --download
python scripts/run_concurrent.py --host 127.0.0.1 --port 5000 --num-clients 5 --files-dir test_files/sprint2 --results-dir results/sprint2 --server-metadata results/s2-server-host.json --network-type loopback --download
python scripts/run_concurrent.py --host 127.0.0.1 --port 5000 --num-clients 10 --files-dir test_files/sprint2 --results-dir results/sprint2 --server-metadata results/s2-server-host.json --network-type loopback --download
```

Mỗi lệnh là một phiên riêng. Bỏ `--download` để chỉ upload. Cấu hình mặc định: 5 client, chunk 65536 byte, không chủ động giới hạn băng thông. CLI cho chọn 1/5/10; API Python cho phép 1–100 để kiểm thử khác.

Các tham số:

| Tham số | Ý nghĩa |
| --- | --- |
| --host | IPv4 server, bắt buộc |
| --port | Mặc định 5000 |
| --num-clients | 1, 5 hoặc 10 |
| --files-dir | Thư mục chứa file .bin |
| --results-dir | Thư mục cha; luôn tạo phiên UUID mới bên trong |
| --download | Tải lại từng file sau upload thành công |
| --server-metadata | JSON export trên đúng máy server |
| --network-type | Wi-Fi, Ethernet, loopback hoặc unknown |
| --timeout | Timeout socket, mặc định 30 giây |
| --sync-timeout | Timeout barrier, mặc định 5 giây; phải nhỏ hơn --timeout |

Không cung cấp metadata server vẫn chạy được nhưng các trường không biết là unknown; chưa đủ hồ sơ môi trường để nghiệm thu LAN. Không lấy hardware client giả làm server.

## 5. Quy trình LAN hai máy

1. Server dùng code concurrent đã được nhóm duyệt; client dùng nhánh runner. Cùng protocol READY/SUCCESS và checksum.
2. Cả hai máy cùng LAN/Wi-Fi. Lấy IPv4 server bằng `ipconfig` trên Windows hoặc `ip addr` trên Linux.
3. Trên server export metadata với IP thật, mạng Wi-Fi/Ethernet thực tế; chạy server `--max-clients 10`.
4. Copy JSON export server sang máy client, ví dụ `results/s2-server-host.json`.
5. Chạy các lệnh trên client, thay 127.0.0.1 bằng IP server, `--network-type` bằng mạng client đang dùng.
6. Kiểm tra mã thoát, `summary.json`, CSV và log server. Dừng server bằng Ctrl+C sau thử nghiệm.

Ví dụ **192.168.1.10 là IP minh họa, phải thay**:

```text
python scripts/run_concurrent.py --host 192.168.1.10 --port 5000 --num-clients 5 --files-dir test_files/sprint2 --results-dir results/sprint2 --server-metadata results/s2-server-host.json --network-type Wi-Fi --download
```

Nếu connection refused/timeout, kiểm tra LISTENING, IP/port, cùng mạng và firewall TCP 5000. Không dùng localhost để kết nối máy khác. Nếu server thiếu slot, có thể gặp SERVER_BUSY; giữ kết quả FAIL, điều chỉnh cấu hình rồi chạy phiên mới. Với 10 client và ba file, có thể cần hơn 610 MB cho download mỗi phiên cộng file server (và bản copy upload nếu không dùng được hard link); kiểm tra dung lượng trước.

## 6. Dữ liệu đầu ra và CSV

```text
results/sprint2/<session_id>/
  environment.json
  summary.json
  runner.log
  all-transfers.csv
  client-01/
    transfers.csv
    worker-result.json
    uploads/<tên riêng>
    downloads/<tên riêng>
  client-02/...
```

Tên trên server chứa **UUID phiên đầy đủ + client_id + tên file gốc**. Không trùng với file nguồn hay worker/phiên khác. Thư mục download riêng. Runner không tự xóa file đã gửi lên server; sau khi giữ chứng cứ, có thể dọn các file `s2_<session_id>_*` của đúng phiên đó.

Mỗi worker có CSV riêng với đúng một writer. Sau khi TẤT CẢ worker kết thúc, thread chính tạo `all-transfers.csv` bằng một writer, kiểm tra schema, số dòng và UUID. Không thread nào ghi file tổng trong lúc truyền. Schema Sprint 1 không đổi, Sprint 2 thêm `client_id`, `session_id`. Không nối vào hoặc ghi đè CSV Sprint 1.

Cột gồm: run_id, timestamp, direction, file_name, file_size_bytes, chunk_size_bytes, num_clients, bandwidth_limit_mbps, transfer_time_s, throughput_mbps, checksum_match, status, environment_id, error_message, client_id, session_id.

- `session_id`: một lần chạy N client; `client_id`: worker trong phiên; `run_id`: một lần thử upload/download.
- `num_clients`: N cấu hình của phiên, cả dòng thành công và lỗi đều ghi N. Đây là số client **được yêu cầu**; số connection thực sự tạo được kiểm tra trong summary, không suy ra từ cột này khi có lỗi.
- `environment_id`: đối chiếu `environment.json` cùng thư mục phiên.
- `SUCCESS`: đủ dữ liệu, completion đúng và checksum_match=true.
- `FAILED`: lỗi kết nối, file, giao thức, timeout, checksum hoặc download bị bỏ qua vì upload lỗi. Thời gian/throughput để trống nếu chưa bắt đầu; FAILED luôn không có throughput hợp lệ.
- `error_message`: nguyên nhân. Download không chạy sau upload lỗi vẫn có dòng FAILED để giữ số lần thử dự kiến.
- Nếu ngay việc khởi tạo worker/ghi đĩa thất bại, có thể không đủ dòng; summary báo lỗi và toàn phiên FAIL, không bịa dòng hay metric để bù.

Số dòng dự kiến = N × số file × (2 nếu --download, ngược lại 1). Ba file: 1 client → 3/6 dòng, 5 → 15/30 dòng, 10 → 30/60 dòng. Header đúng một lần mỗi CSV. Dữ liệu test unit ở thư mục tạm, không lẫn mẫu đo thật.

## 7. Đo thời gian và chứng minh concurrency

Công thức giữ nguyên Sprint 1:

```text
throughput_mbps = file_size_bytes * 8 / (transfer_time_s * 1_000_000)
```

Đây là Mbps (megabit/s), không phải MB/s. Thời lượng từ trước request đến completion + xác minh checksum + rename file download, loại trừ hash nguồn upload. **Upload đầu tiên có tính thời gian chờ gate READY**; do đó dùng kết quả này để nghiệm thu concurrency, không so trực tiếp như benchmark throughput thuần Sprint 1. Các lượt còn lại không chờ gate READY, chỉ khởi đầu worker được đồng bộ một lần.

Các bước chứng minh:

1. Mỗi worker tạo FileClient và socket riêng; summary ghi local/server socket address.
2. Barrier đầu đồng bộ bắt đầu request sau giai đoạn chuẩn bị/kết nối.
3. Với upload đầu tiên, mỗi worker đọc `READY` từ server rồi chờ gate; chưa gửi payload đến khi tất cả worker nhận READY.
4. Chỉ khi server đã dispatch toàn bộ request upload trong lúc các request trước chưa hoàn tất, mọi worker mới qua gate. Server tuần tự bị kẹt ở worker đầu, gate timeout và bị đánh FAIL; runner giải phóng gate để worker còn lại vẫn có thể kết thúc.
5. Ghi mốc `ready_times_s`, `payload_release_times_s` và transfer_start_s/end_s theo perf_counter trên cùng một tiến trình runner.
6. Chỉ PASS khi mọi first upload thành công, gate không vỡ, READY cuối không muộn hơn payload release đầu và cả hai khoảng giao chung dương:
   - `min(first_upload_end) - max(ready_time)`;
   - `min(first_upload_end) - max(payload_release_time)`.

`summary.json` ghi `all_ready_before_payload`, `shared_processing_overlap_s`, `shared_payload_completion_overlap_s` và trạng thái concurrency. Khoảng thứ hai chứng minh các cửa sổ payload/completion chồng lấn sau gate, không chỉ nhiều socket CONNECTED. Mốc perf_counter không phải timestamp lịch và không so giữa hai máy. Đây là bằng chứng concurrent application dispatch/I/O đang chờ, không chứng minh CPU chạy song song từng chu kỳ hay gói tin thực sự xuất hiện cùng lúc trên đường truyền. Có thể đối chiếu log connection_id server và Wireshark khi cần chứng cứ mạng.

File quá nhỏ hoặc tài nguyên máy quá yếu có thể làm khoảng giao sau gate không dương, runner sẽ FAIL thay vì tự kết luận concurrent. Dùng file mặc định 1/10/50 MB và kiểm tra nguyên nhân trước khi tăng timeout. Một worker lỗi sẽ làm toàn kịch bản FAIL nhưng các worker khác vẫn tiếp tục; không biến FAIL thành SUCCESS để làm đẹp số liệu.

## 8. PASS/FAIL và mã thoát

Từng client PASS khi đủ số dòng dự kiến, mọi transfer SUCCESS/checksum true và không có lỗi runtime/CSV. Toàn phiên PASS khi tất cả client PASS, CSV tổng đúng số dòng/UUID/schema và kiểm tra overlap PASS (với 1 client là kiểm tra cơ sở, không khẳng định multi-client).

Mã thoát **0** khi PASS, **1** khi lỗi hoặc concurrency không được chứng minh. PowerShell xem `$LASTEXITCODE`, cmd xem `echo %ERRORLEVEL%`, Linux xem `echo $?` ngay sau lệnh. Thông báo kết quả có đường dẫn thư mục phiên. `runner.log` có kết quả từng client và toàn phiên; `worker-result.json` có lỗi và khoảng thời gian. Console từ các worker có thể xen nhau; dùng CSV/JSON để đọc chính xác.

## 9. Test cases và cách chạy

| Mã | Kiểm chứng |
| --- | --- |
| TC01 | 1 client, upload/download, đúng byte và SHA-256 |
| TC02 | 5 socket độc lập, filename riêng, gate READY và thời gian chồng lấn |
| TC03 | 10 client khi server đủ slot/tài nguyên |
| TC04 | Inject lỗi một worker; bốn worker còn lại vẫn hoàn thành, toàn phiên FAIL |
| TC05 | CSV đủ dòng, UUID không trùng, một header, nhiều phiên tách biệt |
| TC06 | num_clients, session/client IDs, environment_id và metadata đúng |
| TC07 | Lỗi trả code khác 0; subprocess CLI thực tế kiểm tra connection refused |
| Bổ sung | Server tuần tự không PASS nhầm vì request xếp hàng; input sai trả lỗi |

Windows PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

Linux:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Khi chạy độc lập trên main, test runner dùng fixture threaded **chỉ trong test** để kiểm tra giao thức. Nó không thay server production. Để chạy lại các test đó bằng server dependency thật, dùng checkout nhánh `cn21-10` ở thư mục riêng:

Windows (thay đường dẫn bằng đường dẫn thật):

```powershell
$env:CONCURRENT_SERVER_FILE = "C:\Projects\ET4230-server\src\server\server.py"
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -p test_concurrent_runner.py -v
Remove-Item Env:CONCURRENT_SERVER_FILE
```

Linux:

```bash
CONCURRENT_SERVER_FILE=/path/to/ET4230-server/src/server/server.py PYTHONPATH=src python -m unittest discover -s tests -p test_concurrent_runner.py -v
```

Không cần cài pytest. Nếu đã cài dependencies nhóm thì có thể dùng pytest. Bộ test giữ sentinel CSV Sprint 1 không đổi, so sánh byte file upload/download và kiểm tra các đường lỗi. Chi tiết kết quả thực tế trong [sprint2-verification.md](sprint2-verification.md).

## 10. Tương thích FILE_BUSY

Server `a07b950` có nhánh trả FILE_BUSY nếu storage cung cấp try_lock_file. Storage production tại revision đó chưa có API khóa; các test server bổ sung helper riêng. Không coi test fixture là bằng chứng khóa production. Runner dùng tên khác nhau theo worker/phiên; test client bổ sung kiểm tra FILE_BUSY ở cả upload/download được ghi FAILED, throughput trống và cùng socket có thể thử lại thành công. Đây là kiểm chứng xử lý response ở client, không phải triển khai khóa trong storage.
