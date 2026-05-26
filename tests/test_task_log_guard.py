import unittest

from utils import task_log_guard


class TaskLogGuardTests(unittest.TestCase):
    def tearDown(self):
        task_log_guard.end_task()
        task_log_guard.reset_bucket("bucket-a")
        task_log_guard.reset_bucket("bucket-b")
        task_log_guard.clear_batch("batch-a")

    def test_ignored_oauth_401_does_not_increment_counter(self):
        task_log_guard.start_task("bucket-a")
        task_log_guard.observe_log_message("（gm***@***.***）无密码通道OAuth 阶段验证失败: 401")
        self.assertEqual(task_log_guard.get_bucket_count("bucket-a"), 0)

    def test_timeout_reaches_abort_threshold_on_third_hit(self):
        task_log_guard.start_task("bucket-a")
        task_log_guard.bind_task_batch("batch-a")
        timeout_log = (
            "请求失败(第 1 次)Failed to perform, curl: (28) Connection timed out after 15002 milliseconds."
        )

        task_log_guard.observe_log_message(timeout_log)
        task_log_guard.observe_log_message(timeout_log)
        self.assertEqual(task_log_guard.get_bucket_count("bucket-a"), 2)

        with self.assertRaises(task_log_guard.TaskAbortError) as ctx:
            task_log_guard.observe_log_message(timeout_log)

        self.assertEqual(ctx.exception.bucket_id, "bucket-a")
        self.assertEqual(ctx.exception.count, 3)
        self.assertTrue(task_log_guard.is_batch_aborted("batch-a"))

    def test_raise_if_current_batch_aborted_interrupts_peer_worker(self):
        task_log_guard.start_task("bucket-a")
        task_log_guard.bind_task_batch("batch-a")
        task_log_guard.abort_batch("batch-a")

        with self.assertRaises(task_log_guard.BatchAbortError) as ctx:
            task_log_guard.raise_if_current_batch_aborted()

        self.assertEqual("batch-a", ctx.exception.batch_id)

    def test_success_marker_resets_bucket(self):
        task_log_guard.start_task("bucket-b")
        task_log_guard.observe_log_message(
            "请求失败(第 1 次)Failed to perform, curl: (28) Connection timed out after 15002 milliseconds."
        )
        self.assertEqual(task_log_guard.get_bucket_count("bucket-b"), 1)

        task_log_guard.mark_task_success("bucket-b")
        self.assertEqual(task_log_guard.get_bucket_count("bucket-b"), 0)

    def test_submit_email_409_does_not_increment_counter(self):
        task_log_guard.start_task("bucket-b")
        task_log_guard.observe_log_message("（ts***@***.***）提交邮箱环节异常, 返回: 409")
        task_log_guard.observe_log_message("（ts***@***.***）无密码通道邮件发送异常, 返回: 409")
        self.assertEqual(task_log_guard.get_bucket_count("bucket-b"), 0)

    def test_sleep_with_batch_abort_interrupts_without_waiting_full_duration(self):
        task_log_guard.start_task("bucket-a")
        task_log_guard.bind_task_batch("batch-a")
        task_log_guard.abort_batch("batch-a")

        with self.assertRaises(task_log_guard.BatchAbortError):
            task_log_guard.sleep_with_batch_abort(2)


if __name__ == "__main__":
    unittest.main()
