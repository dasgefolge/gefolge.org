import pathlib
import subprocess

EXEC_PATH = pathlib.Path('/opt/git/github.com/dasgefolge/peter-discord/master/target/release/peter')

class CommandError(RuntimeError):
    pass

def cmd(cmd, *args, check=True, expected_response=object()):
    process = subprocess.run([str(EXEC_PATH), cmd, *args], check=check, stdout=subprocess.PIPE)
    response = process.stdout.decode('utf-8').strip()
    if check and response != expected_response:
        raise CommandError('{} command failed with response: {}'.format(cmd, response))
    else:
        if process.returncode == 0 and response == expected_response:
            return True
        else:
            #TODO send email if failed
            return False

# one function for every IPC command implemented in listen_ipc

def add_role(user, role, *, check=True):
    cmd('add-role', str(user.snowflake), str(role), check=check, expected_response='role added')

def channel_msg(channel, msg, *, check=True):
    cmd('channel-msg', str(channel), msg, check=check, expected_response='message sent')

def msg(rcpt, msg, *, check=True):
    cmd('msg', str(rcpt.snowflake), msg, check=check, expected_response='message sent')

def quit(*, check=True):
    cmd('quit', check=check, expected_response='shutdown complete')
