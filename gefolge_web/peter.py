import pathlib
import subprocess

EXEC_PATH = pathlib.Path('/opt/git/github.com/dasgefolge/peter-discord/master/target/release/peter')

class CommandError(RuntimeError):
    pass

def cmd(cmd, *args, expected_response=object()):
    response = subprocess.run([str(EXEC_PATH), cmd, *args], check=True, stdout=subprocess.PIPE).stdout.decode('utf-8').strip()
    if response != expected_response:
        raise CommandError('{} command failed with response: {}'.format(cmd, response))

# one function for every IPC command implemented in listen_ipc

def add_role(user, role):
    cmd('add-role', str(user.snowflake), str(role), expected_response='role added')

def channel_msg(channel, msg):
    cmd('channel-msg', str(channel), msg, expected_response='message sent')

def msg(rcpt, msg):
    cmd('msg', str(rcpt.snowflake), msg, expected_response='message sent')

def quit():
    cmd('quit', expected_response='shutdown complete')
