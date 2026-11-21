# Kiểm chứng tương thích server concurrent

Ngày chạy: 21/11/2026. Runner trên nhánh `ha-nguyet`; server từ nhánh `cn21-10`, commit `a07b9503bb8d942cd16c3b1895ba06f1ecbff88d`. Không thay đổi code hoặc nhánh server/main.

## Môi trường và phạm vi

Linux/container, Python 3.12.14, TCP loopback trên cùng máy. Server max_clients=10, client_timeout=30 giây, chunk client/server 65536 byte, không chủ động giới hạn băng thông. Chưa chạy Windows/Python 3.11 hoặc LAN hai máy. Hướng dẫn Windows nằm tại [README](../README.md).

Code runner chưa commit tại thời điểm đo; metadata có commit nền và source_sha256 để xác định file thực thi. Mẫu công khai không chứa CPU/RAM cụ thể, hostname, IP LAN hoặc đường dẫn cục bộ.

## Kiểm thử

- **54 tests OK** trên nhánh ha-nguyet, gồm bộ Sprint 1 và 10 test concurrent runner. Các ca concurrent dùng implementation server thật tại a07b950; ca đối chứng tuần tự dùng server đi kèm ha-nguyet.
- **60 tests OK** khi chạy suite riêng của server cn21-10 tại a07b950 trong checkout tách biệt.
- Bộ runner độc lập không đặt biến dependency dùng fixture threaded chỉ trong test, không thay server production.

Lệnh kiểm thử runner với server dependency trên Linux:

```bash
CONCURRENT_SERVER_FILE=/path/to/server/src/server/server.py PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -v
```

Test mới kiểm tra FILE_BUSY ở cả upload/download: lượt lỗi ghi FAILED, throughput trống, socket vẫn sử dụng được và retry thành công. Response lỗi được inject có kiểm soát trong test; không giả định storage đã có khóa production.

Các test còn lại kiểm tra 1/5/10 socket độc lập, byte/checksum, số dòng/schema/header/UUID, num_clients/metadata, lỗi một worker không chặn worker khác, CLI nonzero khi lỗi và server tuần tự không PASS nhầm. Sentinel CSV Sprint 1 và các file baseline đã commit không thay đổi.

## Chạy CLI thực tế

Ba file 1/10/50 MB, mỗi worker upload và download trên socket riêng. Không chèn số liệu thủ công vào CSV.

| Client | Dòng CSV | Toàn phiên | Overlap payload/completion chung (giây) |
| --- | --- | --- | --- |
| 1 | 6/6 | PASS | 0.06801049599994258 |
| 5 | 30/30 | PASS | 0.028855159999920943 |
| 10 | 60/60 | PASS | 0.055988908000017545 |

Tất cả 96 lượt truyền SUCCESS, checksum_match=true. Đã đối chiếu thêm SHA-256 trên nguồn, đường dẫn upload worker, file nhận server và download cho 48 cặp file. Với một client, overlap chỉ là kiểm tra cơ sở. Server thử nghiệm đã được dừng.

Mẫu: [results/sprint2-samples](../results/sprint2-samples). Log unittest runner: [test-suite.log](../results/sprint2-samples/test-suite.log). Cửa sổ perf_counter chỉ so trong cùng tiến trình; upload đầu gồm gate wait, không coi là benchmark tốc độ thuần Sprint 1.

## Phụ thuộc còn mở

Server a07b950 chỉ áp dụng FILE_BUSY khi storage cung cấp try_lock_file. FileStorage production hiện chưa có hàm này; các test server tự bổ sung helper khóa. Cần triển khai/review phần storage trước khi tuyên bố bảo vệ file cùng tên. Runner chủ động dùng tên riêng mỗi phiên và worker.

Chưa xác nhận trạng thái S2-01/S2-02/S2-03/S2-04 trên bảng công việc. Kết quả loopback không thay nghiệm thu Windows/LAN; nhóm chạy lại trên hai máy theo README và giữ metadata/CSV/log/PCAP thật. Chỉ nhánh ha-nguyet được cập nhật trong lần kiểm chứng này.
