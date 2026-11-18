# Kết quả kiểm chứng Sprint 2

Ngày kiểm chứng: 18/11/2026. Môi trường thực tế Linux/container, Python 3.12.14, client/server trên cùng máy qua loopback. Chưa chạy hai máy Windows/LAN.

## Revision và phụ thuộc

- Nhánh runner: `ha-nguyet-s2-concurrent`, nền `main` tại `b2e3c9803ab9c9cab13ee4662c005c1461d358a4`.
- Server chạy thật: nhánh `cn21-10`, commit `dd74fe8eb8ce9d541db98f05eea383c1b100997d`.
- Server max_clients=10, client_timeout=30 giây; client/server chunk 65536 byte.
- Không sửa hoặc merge server/main trong nhiệm vụ này. Runner có thể thử server main nhưng server tuần tự phải FAIL khi yêu cầu concurrency.
- Code chưa commit tại thời điểm đo; metadata ghi working_tree_dirty và SHA-256 của các file thực thi để truy vết.

## Kiểm thử

- Trước thay đổi: **49 tests OK**.
- Sau thay đổi: **58 tests OK** gồm 9 test runner mới; suite cuối chạy các test concurrent bằng chính implementation server nhánh `cn21-10`.
- Trước đó suite độc lập với test-only threaded protocol fixture cũng chạy qua.
- Lệnh cuối trên Linux:

```bash
CONCURRENT_SERVER_FILE=/path/to/cn21-10/src/server/server.py PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -v
```

Các kiểm tra mới bao phủ 1/5/10 kết nối, hai file/worker, SHA-256/byte roundtrip, lỗi một worker không ngăn worker khác, schema/header/số dòng/UUID, metadata, mã thoát CLI khi refused và trường hợp server tuần tự không được PASS nhầm. Sentinel CSV Sprint 1 được so byte và giữ nguyên. Chi tiết đầu ra unittest: [test-suite.log](../results/sprint2-samples/test-suite.log).

## Ba phiên CLI với server thật

Mỗi phiên dùng ba file 1/10/50 MB, có upload và download. Các lệnh cùng mẫu:

```text
python scripts/run_concurrent.py --host 127.0.0.1 --port <port-thực> --num-clients <1|5|10> --files-dir <fixtures> --results-dir <thư-mục-riêng> --server-metadata <server-export.json> --network-type loopback --download
```

| Client | CSV | SHA-256 | Mã thoát | Overlap sau gate (giây) |
| --- | --- | --- | --- | --- |
| 1 | 6/6 dòng | Tất cả khớp | 0 | 0.03740258499999527; chỉ là kiểm tra cơ sở |
| 5 | 30/30 dòng | Tất cả khớp | 0 | 0.039136772000006204 |
| 10 | 60/60 dòng | Tất cả khớp | 0 | 0.09685530699999845 |

Các thời lượng trên lấy trực tiếp từ summary chạy thật, không nhập vào CSV như benchmark giả. Mẫu đầy đủ: [results/sprint2-samples](../results/sprint2-samples). Đã đối chiếu thêm SHA-256 trên file nguồn, đường dẫn upload worker, file nhận trên server và download worker cho tất cả 48 cặp file (1+5+10 client × 3 file).

## Giới hạn và công việc tích hợp

- Bằng chứng READY + khoảng thời gian payload/completion chứng minh concurrent application dispatch/I/O, không phải số đo CPU song song hay wire throughput.
- Upload đầu tính thời gian chờ gate; không so như baseline Sprint 1 nguyên trạng.
- Để nghiệm thu LAN, nhóm cần chạy lại trên hai máy theo test plan và lưu metadata thật. Mẫu loopback không thay bằng chứng LAN.
- Cần server concurrent được nhóm duyệt/triển khai; PR runner không tự merge nhánh `cn21-10` vào main.
- Chưa xác định được mapping S2-01/S2-02/S2-03/S2-04 với trạng thái trên bảng công việc; nhóm xác nhận dependency khi review PR.
- Server do các lần kiểm chứng khởi động đã được dừng. Dữ liệu baseline Sprint 1 không bị thay đổi.
