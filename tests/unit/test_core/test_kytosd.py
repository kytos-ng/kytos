"""Test kytos.core.kytosd module."""
import signal
from unittest.mock import MagicMock, patch

from kytos.core.kytosd import (_create_pid_dir, async_main, main, start_shell,
                               stop_controller_sys_exit)


class TestKytosd:
    """Kytosd tests."""

    @staticmethod
    @patch('os.makedirs')
    @patch('kytos.core.kytosd.BASE_ENV', '/tmp/')
    def test_create_pid_dir__env(mock_mkdirs):
        """Test _create_pid_dir method with env."""
        _create_pid_dir()

        mock_mkdirs.assert_called_with('/tmp/var/run/kytos', exist_ok=True)

    @staticmethod
    @patch('os.chmod')
    @patch('os.makedirs')
    @patch('kytos.core.kytosd.BASE_ENV', '/')
    def test_create_pid_dir__system(*args):
        """Test _create_pid_dir method with system dir."""
        (mock_mkdirs, mock_chmod) = args
        _create_pid_dir()

        mock_mkdirs.assert_called_with('/var/run/kytos', exist_ok=True)
        mock_chmod.assert_called_with('/var/run/kytos', 0o1777)

    @staticmethod
    @patch('kytos.core.kytosd.InteractiveShellEmbed')
    def test_start_shell(mock_interactive_shell):
        """Test stop_api_server method."""
        start_shell(MagicMock())

        mock_interactive_shell.assert_called()

    @staticmethod
    @patch('kytos.core.kytosd.async_main')
    @patch('kytos.core.kytosd._create_pid_dir')
    @patch('kytos.core.kytosd.KytosConfig')
    def test_main__foreground(*args):
        """Test main method in foreground."""
        (mock_kytos_config, mock_create_pid_dir, mock_async_main) = args
        config = MagicMock(foreground=True)
        options = {'daemon': config}
        mock_kytos_config.return_value.options = options

        main()

        mock_create_pid_dir.assert_called()
        mock_async_main.assert_called()

    @staticmethod
    @patch('kytos.core.kytosd.daemon.DaemonContext')
    @patch('kytos.core.kytosd.async_main')
    @patch('kytos.core.kytosd._create_pid_dir')
    @patch('kytos.core.kytosd.KytosConfig')
    def test_main__background(*args):
        """Test main method in background."""
        (mock_kytos_config, mock_create_pid_dir, mock_async_main, _) = args
        config = MagicMock(foreground=False)
        options = {'daemon': config}
        mock_kytos_config.return_value.options = options

        main()

        mock_create_pid_dir.assert_called()
        mock_async_main.assert_called()

    @staticmethod
    @patch('kytos.core.kytosd.start_shell_async', spec=MagicMock)
    @patch('kytos.core.kytosd.asyncio')
    @patch('kytos.core.kytosd.InteractiveShellEmbed')
    @patch('kytos.core.kytosd.Controller')
    def test_async_main(*args):
        """Test async_main method."""
        (mock_controller, _, mock_asyncio, _) = args
        controller = MagicMock()
        controller.options.debug = True
        controller.options.foreground = True
        mock_controller.return_value = controller

        event_loop = MagicMock()
        mock_asyncio.new_event_loop.return_value = event_loop

        async_main(MagicMock())

        event_loop.run_until_complete.assert_called_with(controller.start())

    @patch("builtins.open", create=True)
    @patch('kytos.core.kytosd.os')
    def test_stop_controller_sys_exit(self, mock_os, _mock_open) -> None:
        """Test stop the controller sys exit."""
        controller, config = MagicMock(), MagicMock()
        stop_controller_sys_exit(controller, config)
        controller.stop.assert_called()
        mock_os.kill.assert_called()
        assert mock_os.kill.call_args[0][1] == signal.SIGTERM
