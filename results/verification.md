# Kết quả kiểm chứng Sprint 1

- Ngày chạy: 11/11/2026, khoảng 20:39 giờ Việt Nam (CSV lưu UTC có múi giờ).
- Nhánh làm việc: `ha-nguyet`; nền commit `e646e474355ad3a32d9227fd37600b24a41fe0bd`.
- Code đo có thay đổi chưa commit: `working_tree_dirty=true`. Giữ phiên bản code đo cùng kết quả; không suy ra code đo chỉ từ nền commit.
- Python thực tế: **3.12.14**, Linux/container; chưa kiểm chứng Python 3.11 trên Windows.
- Server và client chạy trên **cùng máy**, TCP `127.0.0.1:5000`, mạng **loopback**.
- Một client, client/server chunk **65536 byte**, không chủ động giới hạn băng thông.
- File thử tạo bằng generator, đúng **1.000.000 / 10.000.000 / 50.000.000 byte**.
- Đã chạy thật `scripts/run_baseline.py --host 127.0.0.1 --port 5000 --network-type loopback --server-metadata results/server-host.json --download`.
- Kết quả: **6 lượt SUCCESS**, 3 upload + 3 download; tất cả checksum_match=true. Không nhập tay các dòng CSV.
- CSV gốc: `raw/baseline.csv`; metadata UUID `009334f1-cf22-41e1-8ae3-4c2dbb9a8354` ở `environments/`.
- Ghi lại terminal client: `baseline-terminal.txt`; log server: `baseline-server.jsonl`.
- Trước sửa: **33 tests OK**. Sau sửa: **44 tests OK**, gồm 11 tests mới.
- Lệnh kiểm thử cuối: `PYTHONPATH=src python -W error::ResourceWarning -m unittest discover -s tests -v`.
- Kết quả kiểm thử ở `test-results.txt`; dữ liệu test dùng thư mục tạm, tách baseline.
- Server thử nghiệm đã được dừng sau khi đo.

## Đối chiếu nghiệm thu

| Yêu cầu | Kết quả |
| --- | --- |
| File đúng kích thước | Đã tạo và kiểm tra đủ ba file |
| perf_counter và công thức Mbps | Helper dùng chung, đã kiểm thử |
| CSV tự động, UUID mỗi transfer | Đã kiểm tra header, append, UUID và CSV thật |
| Checksum và SUCCESS/FAILED | Đã kiểm tra thành công, mismatch, checksum không hợp lệ, timeout và lỗi tiền xử lý |
| Metadata | Lưu cả client/server cùng snapshot theo UUID |
| Baseline ba kích thước | Có số liệu thật loopback, cả upload/download |
| Không bịa số liệu | CSV phát sinh trực tiếp từ truyền TCP thật |

## Việc người dùng cần làm tiếp

1. Checkout nhánh `ha-nguyet` và chuẩn bị môi trường Python.
2. Đọc `report/measurement-guide.md` và chạy thử theo phần một máy.
3. Đo lại trên hai máy của nhóm, export metadata server trên đúng máy, dùng `--csv results/raw/lan-baseline.csv` để giữ riêng số liệu LAN.
4. Giữ nguyên CSV loopback để truy vết, không đổi network_type thành Wi-Fi/Ethernet.
5. Giữ kết quả loopback và LAN trong các CSV riêng để so sánh và truy vết.

Kết quả loopback chỉ kiểm chứng luồng xử lý; throughput không đại diện cho Wi-Fi/Ethernet hay tốc độ đường truyền vật lý. Chưa có minh chứng LAN/Wireshark, thống kê hoặc multi-client; các phần này không được giả định là đã hoàn thành.
