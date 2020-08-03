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
            #TODO send email
            return False

def escape(text):
    text = str(text)
    #FROM https://docs.rs/serenity/0.7.4/src/serenity/utils/message_builder.rs.html#556-568
    # Remove invite links and popular scam websites, mostly to prevent the
    # current user from triggering various ad detectors and prevent embeds.
    text = text.replace('discord.gg', 'discord\u2024gg')
    text = text.replace('discord.me', 'discord\u2024me')
    text = text.replace('discordlist.net', 'discordlist\u2024net')
    text = text.replace('discordservers.com', 'discordservers\u2024com')
    text = text.replace('discordapp.com/invite', 'discordapp\u2024com/invite')
    text = text.replace('discord.com/invite', 'discord\u2024com/invite')
    # Remove right-to-left override and other similar annoying symbols
    text = text.replace('\u202e', ' ') # RTL Override
    text = text.replace('\u200f', ' ') # RTL Mark
    text = text.replace('\u202b', ' ') # RTL Embedding
    text = text.replace('\u200b', ' ') # Zero-width space
    text = text.replace('\u200d', ' ') # Zero-width joiner
    text = text.replace('\u200c', ' ') # Zero-width non-joiner
    # Remove everyone and here mentions. Has to be put after ZWS replacement
    # because it utilises it itself.
    text = text.replace('@everyone', '@\u200beveryone')
    text = text.replace('@here', '@\u200bhere')
    return text.replace('*', '\\*').replace('`', '\\`').replace('_', '\\_')

# one function for every IPC command implemented in listen_ipc

def add_role(user, role, *, check=True):
    cmd('add-role', str(user.snowflake), str(role), check=check, expected_response='role added')

def channel_msg(channel, msg, *, check=True):
    cmd('channel-msg', str(channel), msg, check=check, expected_response='message sent')

def msg(rcpt, msg, *, check=True):
    cmd('msg', str(rcpt.snowflake), msg, check=check, expected_response='message sent')

def quit(*, check=True):
    cmd('quit', check=check, expected_response='shutdown complete')

def set_display_name(user, display_name):
    cmd('set-display-name', str(user.snowflake), display_name, expected_response='display name set')
