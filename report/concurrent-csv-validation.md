# Concurrent runner — xác thực CSV trước PASS

## Lỗi được sửa

Runner trước đây kiểm tra schema, số dòng và trạng thái SUCCESS/checksum nhưng chưa đối chiếu đầy đủ nội dung từng dòng. CSV có đúng header/số dòng vẫn có thể dẫn đến PASS khi num_clients sai, metadata/định danh không khớp, hoặc file_size_bytes sai nhưng throughput được tính lại nhất quán với số byte sai đó.

Bản sửa thêm validate_worker_rows trước khi kết luận kết quả worker. Không chỉnh số liệu để làm PASS; dòng lỗi được giữ và worker/scenario trả FAIL, exit code khác 0.

## Các điều kiện được kiểm tra

- Đủ và không lặp các cặp direction/filename trong kế hoạch của worker.
- run_id là UUID; timestamp ISO 8601 có múi giờ.
- client_id, session_id, environment_id, num_clients và chunk_size_bytes khớp cấu hình thực tế.
- file_size_bytes khớp fixture nguồn nếu biết; dòng SUCCESS bắt buộc có kích thước đúng.
- SUCCESS có checksum_match=true, thời gian hữu hạn dương, throughput hữu hạn không âm và đúng công thức Mbps.
- FAILED có error_message và không có throughput. Lỗi trước khi biết kích thước được phép để trống file_size_bytes/time.

Công thức không đổi:

```text
throughput_mbps = file_size_bytes * 8 / (transfer_time_s * 1_000_000)
```

## Hành vi được giữ

Mỗi worker tiếp tục ghi CSV riêng, thread chính tổng hợp sau khi tất cả worker kết thúc. Schema Sprint 1 và CSV logger/measurement helper không đổi. READY gate, connection riêng, filename/download riêng và exit code giữ nguyên. Các test dùng thư mục tạm, không ghi vào baseline hoặc mẫu benchmark đã commit.

Không sửa Client Reliability, Server, Storage hoặc protocol. Không đưa source PR #10 đang mở vào bugfix này. Nhánh fix được tách từ main 3c53731; chỉ gồm runner, test CSV và tài liệu này.

## Kiểm chứng

Từ thư mục gốc, với pytest 8.4.2:

Linux:

```bash
PYTHONPATH=src python -m pytest -q tests/test_concurrent_runner.py
PYTHONPATH=src python -m pytest -q tests
```

Windows cmd:

```bat
set PYTHONPATH=src
py -3.11 -m pytest -q tests/test_concurrent_runner.py
py -3.11 -m pytest -q tests
```

Các test CSV mới gồm validator với dòng hợp lệ/lỗi và ba ca end-to-end: ghi sai num_clients, metric NaN, sai kích thước nhưng tính Mbps khớp. Cả ba ca phải trả FAIL/nonzero. Các test concurrency hiện có dùng Server/Storage production từ main; fixture tuần tự chỉ làm đối chứng âm.

Kết quả chạy cụ thể và phiên bản Python được ghi trong PR. Kiểm tra CSV này không thay chứng minh nội dung file bằng SHA-256, không đánh dấu nghiệm thu Windows/LAN và không thay xác nhận review của nhóm.

Kiểm chứng ngày 26/11/2026 trên Linux với pytest 8.4.2: **140 tests PASS trên Python 3.11.17**, **140 tests PASS trên Python 3.12.14**. Nhánh có thêm tám test CSV so với main: ba ca end-to-end và năm test validator. Chưa chạy Windows/LAN trong PR bugfix này.
