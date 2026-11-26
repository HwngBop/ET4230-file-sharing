# CN21-13 — Kiểm chứng phần chuẩn bị độc lập

> Bản ghi lịch sử. Kiểm chứng source đã tích hợp ngày 26/11: [kết quả mới](sprint2-integration-verification.md).

Ngày chạy: 23/11/2026. Nhánh: `ha-nguyet`. Chỉ thay đổi runner và test runner; không ghép PR #8, không rebase, không sửa client.py, Server, Storage hoặc wire protocol.

## Thay đổi thực thi

- Đối chiếu `file_size_bytes` trong CSV với kích thước fixture dự kiến, không chỉ kiểm tra công thức Mbps. Dòng ghi sai byte nhưng tính lại Mbps khớp vẫn phải FAIL.
- Kiểm tra run_id là UUID và timestamp có múi giờ.
- Dòng FAILED phải có error_message và không có throughput; cho phép kích thước chưa biết khi lỗi xảy ra trước khi đọc được file.
- Giữ kiểm tra client/session/environment IDs, num_clients, chunk và danh sách thao tác dự kiến.

Bổ sung sáu test, gồm một test end-to-end inject CSV sai kích thước nhưng rate nhất quán; năm test validator cho input hợp lệ, UUID/timezone, kích thước, lý do lỗi và thao tác thiếu/lặp. Dữ liệu inject chỉ ở thư mục test tạm, không nằm trong mẫu đo thật.

## Kết quả

**62 tests PASS** bằng pytest 8.4.2 với implementation server a07b950 làm dependency kiểm tra. Python thực tế 3.12.14, Linux/container. Đây không phải kết quả Windows/Python 3.11.

```bash
CONCURRENT_SERVER_FILE=/path/to/server/src/server/server.py PYTHONPATH=src python -m pytest -q
```

Chạy độc lập không đặt CONCURRENT_SERVER_FILE cũng đạt **18/18 test runner PASS** với fixture threaded riêng; log [preparation-default-tests-2026-11-23.log](../results/sprint2-samples/preparation-default-tests-2026-11-23.log).

Log pytest: [preparation-pytest-2026-11-23.log](../results/sprint2-samples/preparation-pytest-2026-11-23.log).

Đã chạy CLI thật 1/5/10 client với server a07b950, mỗi worker upload/download ba file 1/10/50 MB qua loopback:

| Client | Dòng CSV | Kết quả |
| --- | --- | --- |
| 1 | 6/6 | PASS |
| 5 | 30/30 | PASS |
| 10 | 60/60 | PASS |

Đã đọc lại và đối chiếu SHA-256 trên nguồn, file upload của worker, file nhận server và download cho 48 cặp file; tất cả 96 transfer SUCCESS/checksum true. Biên nhận kiểm chứng: [preparation-runs-2026-11-23.json](../results/sprint2-samples/preparation-runs-2026-11-23.json). Bản gốc mỗi phiên được giữ cục bộ; biên nhận công khai chỉ chứa định danh/kết quả, source hashes và điều kiện loopback, không có hostname, IP LAN hoặc cấu hình hardware riêng.

Mẫu CSV ngày 22/11 và baseline Sprint 1 được giữ nguyên, không đổi timestamp để thể hiện lần chạy mới. Server thử nghiệm đã dừng.

## Phần còn để lại

PR #8 chưa merge tại lúc bắt đầu công việc. Không dùng kết quả trên để xác nhận Client Reliability mới hoặc Backend locked(...) đã tích hợp. Các bước còn chờ: PR #8 merge, Team Lead chốt luồng PR #6/ha-nguyet, ghép đủ tính năng client.py, regression bản tích hợp và Windows/LAN. Xem [kế hoạch thực hiện](sprint2-execution-plan.md).

Trạng thái: **phần chuẩn bị độc lập đã hoàn thành và kiểm chứng; nghiệm thu tổng thể vẫn PENDING.**
