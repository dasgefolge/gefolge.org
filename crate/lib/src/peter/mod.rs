use {
    std::{
        collections::{
            BTreeSet,
            HashMap,
        },
        iter,
        pin::{
            Pin,
            pin,
        },
        time::Duration,
    },
    futures::{
        future::{
            Future,
            TryFutureExt as _,
        },
        stream::TryStreamExt as _,
    },
    itertools::Itertools as _,
    rand::{
        prelude::*,
        rng,
    },
    serde_json::json,
    serenity::{
        all::{
            CreateCommand,
            CreateCommandOption,
            CreateInteractionResponse,
            CreateInteractionResponseMessage,
            EditMember,
        },
        model::prelude::*,
        prelude::*,
        utils::MessageBuilder,
    },
    serenity_utils::{
        builder::ErrorNotifier,
        handler::{
            HandlerMethods as _,
            voice_state::VoiceStates,
        },
    },
    sqlx::PgPool,
    tokio::time::{
        Instant,
        sleep,
    },
    wheel::{
        fs,
        traits::IsNetworkError,
    },
    crate::config::Config,
};

mod ipc;
mod lang;
mod parse;
pub(crate) mod twitch;
mod user_list;
pub(crate) mod werewolf;

const GEFOLGE: GuildId = GuildId::new(355761290809180170);

const QUIZMASTER: RoleId = RoleId::new(847443327069454378);
pub const MENSCH: RoleId = RoleId::new(386753710434287626);
pub const GUEST: RoleId = RoleId::new(784929665478557737);

const FENHL: UserId = UserId::new(86841168427495424);

const TEAMS: [RoleId; 6] = [
    RoleId::new(828431321586991104),
    RoleId::new(828431500747735100),
    RoleId::new(828431624759935016),
    RoleId::new(828431736194072606),
    RoleId::new(828431741332750407),
    RoleId::new(828431913738960956),
];

/// `typemap` key for the PostgreSQL database connection.
struct Database;

impl TypeMapKey for Database {
    type Value = PgPool;
}

enum VoiceStateExporter {}

impl serenity_utils::handler::voice_state::ExporterMethods for VoiceStateExporter {
    fn dump_info<'a>(_: &'a Context, guild_id: GuildId, VoiceStates(voice_states): &'a VoiceStates) -> Pin<Box<dyn Future<Output = Result<(), Box<dyn std::error::Error + Send + Sync>>> + Send + 'a>> {
        Box::pin(async move {
            if guild_id != GEFOLGE { return Ok(()) }
            let buf = serde_json::to_vec_pretty(&json!({
                "channels": voice_states.into_iter()
                    .map(|(channel_id, (channel_name, members))| json!({
                        "members": members.into_iter()
                            .map(|user| json!({
                                "discriminator": user.discriminator,
                                "snowflake": user.id,
                                "username": user.name,
                            }))
                            .collect_vec(),
                        "name": channel_name,
                        "snowflake": channel_id,
                    }))
                    .collect_vec()
            }))?;
            fs::write("/usr/local/share/fidera/discord/voice-state.json", buf).await?;
            Ok(())
        })
    }

    fn ignored_channels<'a>(ctx: &'a Context) -> Pin<Box<dyn Future<Output = Result<BTreeSet<ChannelId>, Box<dyn std::error::Error + Send + Sync>>> + Send + 'a>> {
        Box::pin(async move {
            let data = ctx.data.read().await;
            Ok(data.get::<Config>().expect("missing config").discord.channels.ignored.clone())
        })
    }

    fn notify_start<'a>(ctx: &'a Context, user_id: UserId, guild_id: GuildId, channel_id: ChannelId) -> Pin<Box<dyn Future<Output = Result<(), Box<dyn std::error::Error + Send + Sync>>> + Send + 'a>> {
        Box::pin(async move {
            if guild_id != GEFOLGE { return Ok(()) }
            let data = ctx.data.read().await;
            let config = data.get::<Config>().expect("missing config");
            let mut msg_builder = MessageBuilder::default();
            msg_builder.push("Discord Party? ");
            msg_builder.mention(&user_id);
            msg_builder.push(" ist jetzt im voice channel ");
            msg_builder.mention(&channel_id);
            config.discord.channels.voice.say(&ctx, msg_builder.build()).await?;
            Ok(())
        })
    }
}

#[derive(Clone, Copy)]
pub(crate) struct CommandIds {
    day: CommandId,
    iam: Option<CommandId>,
    iamn: Option<CommandId>,
    r#in: CommandId,
    night: CommandId,
    out: CommandId,
    ping: Option<CommandId>,
    reset_quiz: Option<CommandId>,
    team: Option<CommandId>,
}

impl TypeMapKey for CommandIds {
    type Value = HashMap<GuildId, CommandIds>;
}

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error(transparent)] QwwStartGame(#[from] quantum_werewolf::game::state::StartGameError),
    #[error(transparent)] Serenity(#[from] serenity::Error),
    #[error(transparent)] Twitch(#[from] twitch_helix::Error),
    #[error("invalid game action: {0}")]
    GameAction(String),
    /// Returned if the config is not present in Serenity context.
    #[error("config missing in Serenity context")]
    MissingConfig,
    #[error("Twitch returned unexpected user info")]
    TwitchUserLookup,
}

impl IsNetworkError for Error {
    fn is_network_error(&self) -> bool {
        match self {
            | Self::QwwStartGame(_)
            | Self::GameAction(_)
            | Self::MissingConfig
            | Self::TwitchUserLookup
                => false,
            Self::Serenity(e) => match e {
                serenity::Error::Http(HttpError::Request(e)) => e.is_request() || e.is_connect() || e.is_timeout() || e.status().is_some_and(|status| status.is_server_error()),
                serenity::Error::Io(e) => e.is_network_error(),
                serenity::Error::Tungstenite(e) => e.is_network_error(),
                _ => false,
            },
            Self::Twitch(e) => match e {
                twitch_helix::Error::ExactlyOne(_) | twitch_helix::Error::InvalidHeaderValue(_) | twitch_helix::Error::ResponseJson(_, _) => false,
                twitch_helix::Error::HttpStatus(e, _) | twitch_helix::Error::Reqwest(e) => e.is_network_error(),
            },
        }
    }
}

#[allow(deprecated)] //TODO remove use of CreateCommand::dm_permission once CreateCommand::contexts is no longer unstable Discord API
pub async fn configure_builder(discord_builder: serenity_utils::Builder, config: Config, db_pool: PgPool, shutdown: rocket::Shutdown) -> Result<serenity_utils::Builder, Error> {
    discord_builder
    .error_notifier(ErrorNotifier::User(FENHL))
    .event_handler(serenity_utils::handler::user_list_exporter::<user_list::Exporter>())
    .event_handler(serenity_utils::handler::voice_state_exporter::<VoiceStateExporter>())
    .plain_message(|ctx, msg| Box::pin(async move {
        (msg.guild_id.is_none() || ctx.data.read().await.get::<Config>().expect("missing config").discord.werewolf.iter().any(|(_, conf)| conf.text_channel == msg.channel_id)) && {
            if let Some(action) = werewolf::parse_action(ctx, msg.author.id, &msg.content).await {
                match async move { action }.and_then(|action| werewolf::handle_action(ctx, msg, action)).await {
                    Ok(()) => {} // reaction is posted in handle_action
                    Err(Error::GameAction(err_msg)) => { msg.reply(ctx, &err_msg).await.expect("failed to reply to game action"); }
                    Err(e) => { panic!("failed to handle game action: {}", e); }
                }
                true
            } else {
                false
            }
        }
    }))
    .unrecognized_message("ich habe diese Nachricht nicht verstanden")
    .on_guild_create(false, |ctx, guild, _| Box::pin(async move {
        let mut commands = Vec::default();
        let day = {
            let idx = commands.len();
            commands.push(CreateCommand::new("day")
                .kind(CommandType::ChatInput)
                .dm_permission(false)
                .description("In Quantenwerwölfe den nächsten Tag starten")
            );
            idx
        };
        let iam = (guild.id == GEFOLGE).then(|| {
            let idx = commands.len();
            commands.push(CreateCommand::new("iam")
                .kind(CommandType::ChatInput)
                .dm_permission(false)
                .description("Dir eine selbstzuweisbare Rolle zuweisen")
                .add_option(CreateCommandOption::new(
                    CommandOptionType::Role,
                    "role",
                    "die Rolle, die du haben möchtest",
                ).required(true))
            );
            idx
        });
        let iamn = (guild.id == GEFOLGE).then(|| {
            let idx = commands.len();
            commands.push(CreateCommand::new("iamn")
                .kind(CommandType::ChatInput)
                .dm_permission(false)
                .description("Eine selbstzuweisbare Rolle von dir entfernen")
                .add_option(CreateCommandOption::new(
                    CommandOptionType::Role,
                    "role",
                    "die Rolle, die du loswerden möchtest",
                ).required(true))
            );
            idx
        });
        let r#in = {
            let idx = commands.len();
            commands.push(CreateCommand::new("in")
                .kind(CommandType::ChatInput)
                .dm_permission(false)
                .description("Bei Quantenwerwölfe mitspielen")
            );
            idx
        };
        let night = {
            let idx = commands.len();
            commands.push(CreateCommand::new("night")
                .kind(CommandType::ChatInput)
                .dm_permission(false)
                .description("In Quantenwerwölfe die nächste Nacht starten")
            );
            idx
        };
        let out = {
            let idx = commands.len();
            commands.push(CreateCommand::new("out")
                .kind(CommandType::ChatInput)
                .dm_permission(false)
                .description("Von Quantenwerwölfe aussteigen")
            );
            idx
        };
        let ping = (guild.id == GEFOLGE).then(|| {
            let idx = commands.len();
            commands.push(CreateCommand::new("ping")
                .kind(CommandType::ChatInput)
                .dm_permission(false)
                .description("Testen, ob Peter online ist")
            );
            idx
        });
        let reset_quiz = (guild.id == GEFOLGE).then(|| {
            let idx = commands.len();
            commands.push(CreateCommand::new("reset-quiz")
                .kind(CommandType::ChatInput)
                .dm_permission(false)
                .description("Die Rollen und Nicknames für Quizmaster und Teams aufräumen")
            );
            idx
        });
        let team = (guild.id == GEFOLGE).then(|| {
            let idx = commands.len();
            commands.push(CreateCommand::new("team")
                .kind(CommandType::ChatInput)
                .dm_permission(false)
                .description("In ein Team wechseln, z.B. für ein Quiz")
                .add_option(CreateCommandOption::new(
                    CommandOptionType::Integer,
                    "team",
                    "Die Teamnummer",
                )
                    .required(true)
                    .min_int_value(1)
                    .max_int_value(6)
                )
            );
            idx
        });
        let commands = guild.set_commands(ctx, commands).await?;
        ctx.data.write().await.entry::<CommandIds>().or_default().insert(guild.id, CommandIds {
            day: commands[day].id,
            iam: iam.map(|idx| commands[idx].id),
            iamn: iamn.map(|idx| commands[idx].id),
            r#in: commands[r#in].id,
            night: commands[night].id,
            out: commands[out].id,
            ping: ping.map(|idx| commands[idx].id),
            reset_quiz: reset_quiz.map(|idx| commands[idx].id),
            team: team.map(|idx| commands[idx].id),
        });
        Ok(())
    }))
    .on_interaction_create(|ctx, interaction| Box::pin(async move {
        match interaction {
            Interaction::Command(interaction) => {
                let guild_id = interaction.guild_id.expect("Discord slash command called outside of a guild");
                if let Some(&command_ids) = ctx.data.read().await.get::<CommandIds>().and_then(|command_ids| command_ids.get(&guild_id)) {
                    if interaction.data.id == command_ids.day {
                        match werewolf::channel_check(ctx, &interaction).await {
                            Ok(guild) => {
                                let data = ctx.data.read().await;
                                let conf = *data.get::<Config>().expect("missing config").discord.werewolf.get(&guild).expect("unconfigured guild but check passed");
                                if let Some(voice_channel) = conf.voice_channel {
                                    let voice_states = data.get::<VoiceStates>().expect("missing voice states map");
                                    let VoiceStates(ref chan_map) = voice_states;
                                    if let Some((_, users)) = chan_map.get(&voice_channel) {
                                        for user in users {
                                            guild.edit_member(ctx, user, EditMember::default().mute(false)).await?;
                                        }
                                    }
                                }
                            }
                            Err(response) => interaction.create_response(ctx, CreateInteractionResponse::Message(CreateInteractionResponseMessage::new()
                                .ephemeral(true)
                                .content(response)
                            )).await?,
                        }
                    } else if Some(interaction.data.id) == command_ids.iam {
                        let member = interaction.member.clone().expect("/iam called outside of a guild");
                        let role_id = match interaction.data.options[0].value {
                            CommandDataOptionValue::Role(role) => role,
                            _ => panic!("unexpected slash command option type"),
                        };
                        let response = if !ctx.data.read().await.get::<Config>().expect("missing self-assignable roles list").discord.self_assignable_roles.contains(&role_id) {
                            "diese Rolle ist nicht selbstzuweisbar"
                        } else if member.roles.contains(&role_id) {
                            "du hast diese Rolle schon"
                        } else {
                            member.add_role(&ctx, role_id).await?;
                            "✅"
                        };
                        interaction.create_response(ctx, CreateInteractionResponse::Message(CreateInteractionResponseMessage::new()
                            .ephemeral(true)
                            .content(response)
                        )).await?;
                    } else if Some(interaction.data.id) == command_ids.iamn {
                        let member = interaction.member.clone().expect("/iamn called outside of a guild");
                        let role_id = match interaction.data.options[0].value {
                            CommandDataOptionValue::Role(role) => role,
                            _ => panic!("unexpected slash command option type"),
                        };
                        let response = if !ctx.data.read().await.get::<Config>().expect("missing self-assignable roles list").discord.self_assignable_roles.contains(&role_id) {
                            "diese Rolle ist nicht selbstzuweisbar"
                        } else if !member.roles.contains(&role_id) {
                            "du hast diese Rolle sowieso nicht"
                        } else {
                            member.remove_role(&ctx, role_id).await?;
                            "✅"
                        };
                        interaction.create_response(ctx, CreateInteractionResponse::Message(CreateInteractionResponseMessage::new()
                            .ephemeral(true)
                            .content(response)
                        )).await?;
                    } else if interaction.data.id == command_ids.r#in {
                        match werewolf::channel_check(ctx, &interaction).await {
                            Ok(guild) => {
                                {
                                    let mut data = ctx.data.write().await;
                                    let conf = *data.get::<Config>().expect("missing config").discord.werewolf.get(&guild).expect("unconfigured guild but check passed");
                                    let state = data.get_mut::<werewolf::GameState>().expect("missing Werewolf game state");
                                    if state.iter().any(|(&iter_guild, iter_state)| iter_guild != guild && iter_state.state.secret_ids().map_or(false, |secret_ids| secret_ids.contains(&interaction.user.id))) {
                                        interaction.create_response(ctx, CreateInteractionResponse::Message(CreateInteractionResponseMessage::new()
                                            .ephemeral(true)
                                            .content("du bist schon in einem Spiel auf einem anderen Server")
                                        )).await?;
                                        return Ok(())
                                    }
                                    let state = state.entry(guild).or_insert_with(|| werewolf::GameState::new(guild, conf));
                                    if let werewolf::State::Complete(_) = state.state {
                                        state.state = werewolf::State::default();
                                    }
                                    if let werewolf::State::Signups(ref mut signups) = state.state {
                                        // sign up for game
                                        if !signups.sign_up(interaction.user.id) {
                                            interaction.create_response(ctx, CreateInteractionResponse::Message(CreateInteractionResponseMessage::new()
                                                .ephemeral(true)
                                                .content("du bist schon angemeldet")
                                            )).await?;
                                            return Ok(())
                                        }
                                        // add DISCUSSION_ROLE
                                        let roles = iter::once(conf.role).chain(interaction.member.as_ref().unwrap().roles.iter().copied());
                                        guild.edit_member(&ctx, interaction.user.id, EditMember::default().roles(roles)).await?;
                                        interaction.create_response(ctx, CreateInteractionResponse::Message(CreateInteractionResponseMessage::new()
                                            .ephemeral(false)
                                            .content("✅")
                                        )).await?;
                                    } else {
                                        interaction.create_response(ctx, CreateInteractionResponse::Message(CreateInteractionResponseMessage::new()
                                            .ephemeral(true)
                                            .content("bitte warte, bis das aktuelle Spiel vorbei ist")
                                        )).await?;
                                        return Ok(())
                                    }
                                }
                                werewolf::continue_game(&ctx, guild).await?;
                            }
                            Err(response) => interaction.create_response(ctx, CreateInteractionResponse::Message(CreateInteractionResponseMessage::new()
                                .ephemeral(true)
                                .content(response)
                            )).await?,
                        }
                    } else if interaction.data.id == command_ids.night {
                        match werewolf::channel_check(ctx, &interaction).await {
                            Ok(guild) => {
                                let data = ctx.data.read().await;
                                let conf = *data.get::<Config>().expect("missing config").discord.werewolf.get(&guild).expect("unconfigured guild but check passed");
                                if let Some(voice_channel) = conf.voice_channel {
                                    let voice_states = data.get::<VoiceStates>().expect("missing voice states map");
                                    let VoiceStates(ref chan_map) = voice_states;
                                    if let Some((_, users)) = chan_map.get(&voice_channel) {
                                        for user in users {
                                            if *user != interaction.user {
                                                guild.edit_member(ctx, user, EditMember::default().mute(true)).await?;
                                            }
                                        }
                                    }
                                }
                            }
                            Err(response) => interaction.create_response(ctx, CreateInteractionResponse::Message(CreateInteractionResponseMessage::new()
                                .ephemeral(true)
                                .content(response)
                            )).await?,
                        }
                    } else if interaction.data.id == command_ids.out {
                        match werewolf::channel_check(ctx, &interaction).await {
                            Ok(guild) => {
                                {
                                    let mut data = ctx.data.write().await;
                                    let conf = *data.get::<Config>().expect("missing config").discord.werewolf.get(&guild).expect("unconfigured guild but check passed");
                                    let state = data.get_mut::<werewolf::GameState>().expect("missing Werewolf game state").entry(guild).or_insert_with(|| werewolf::GameState::new(guild, conf));
                                    if let werewolf::State::Complete(_) = state.state {
                                        state.state = werewolf::State::default();
                                    }
                                    if let werewolf::State::Signups(ref mut signups) = state.state {
                                        if !signups.remove_player(&interaction.user.id) {
                                            interaction.create_response(ctx, CreateInteractionResponse::Message(CreateInteractionResponseMessage::new()
                                                .ephemeral(true)
                                                .content("du warst nicht angemeldet")
                                            )).await?;
                                            return Ok(())
                                        }
                                        // remove DISCUSSION_ROLE
                                        let roles = interaction.member.as_ref().unwrap().roles.iter().copied().filter(|&role| role != conf.role);
                                        guild.edit_member(&ctx, interaction.user.id, EditMember::default().roles(roles)).await?;
                                        interaction.create_response(ctx, CreateInteractionResponse::Message(CreateInteractionResponseMessage::new()
                                            .ephemeral(false)
                                            .content("✅")
                                        )).await?;
                                    } else {
                                        interaction.create_response(ctx, CreateInteractionResponse::Message(CreateInteractionResponseMessage::new()
                                            .ephemeral(true)
                                            .content("bitte warte, bis das aktuelle Spiel vorbei ist") //TODO implement forfeiting
                                        )).await?;
                                        return Ok(())
                                    }
                                }
                                werewolf::continue_game(&ctx, guild).await?;
                            }
                            Err(response) => interaction.create_response(ctx, CreateInteractionResponse::Message(CreateInteractionResponseMessage::new()
                                .ephemeral(true)
                                .content(response)
                            )).await?,
                        }
                    } else if Some(interaction.data.id) == command_ids.ping {
                        interaction.create_response(ctx, CreateInteractionResponse::Message(CreateInteractionResponseMessage::new()
                            .ephemeral(true)
                            .content({
                                let mut rng = rng();
                                if rng.random_bool(0.01) {
                                    format!("BWO{}{}G", "R".repeat(rng.random_range(3..20)), "N".repeat(rng.random_range(1..5)))
                                } else {
                                    format!("pong")
                                }
                            })
                        )).await?;
                    } else if Some(interaction.data.id) == command_ids.reset_quiz {
                        let mut members = pin!(guild_id.members_iter(ctx));
                        while let Some(member) = members.try_next().await? {
                            member.remove_roles(&ctx, &iter::once(QUIZMASTER).chain(TEAMS).collect_vec()).await?;
                            //TODO adjust nickname
                        }
                        interaction.create_response(ctx, CreateInteractionResponse::Message(CreateInteractionResponseMessage::new()
                            .ephemeral(true)
                            .content("Teams aufgeräumt")
                        )).await?;
                    } else if Some(interaction.data.id) == command_ids.team {
                        let member = interaction.member.clone().expect("/team called outside of a guild");
                        let team = match interaction.data.options[0].value {
                            CommandDataOptionValue::Integer(team) => team,
                            _ => panic!("unexpected slash command option type"),
                        };
                        let team_idx = (team - 1) as usize;
                        member.remove_roles(&ctx, &TEAMS.iter().enumerate().filter_map(|(idx, &role_id)| (idx != team_idx).then(|| role_id)).collect_vec()).await?;
                        member.add_role(ctx, TEAMS[team_idx]).await?;
                        //TODO adjust nickname
                        interaction.create_response(ctx, CreateInteractionResponse::Message(CreateInteractionResponseMessage::new()
                            .ephemeral(true)
                            .content(format!("du bist jetzt in Team {team}"))
                        )).await?;
                    } else {
                        panic!("unexpected slash command")
                    }
                }
            }
            Interaction::Component(_) => panic!("received message component interaction even though no message components are registered"),
            _ => {}
        }
        Ok(())
    }))
    .data::<Config>(config)
    .data::<Database>(db_pool)
    .data::<werewolf::GameState>(HashMap::default())
    .task(|ctx_fut, notify_thread_crash| async move {
        // check Twitch stream status
        let mut last_crash = Instant::now();
        let mut wait_time = Duration::from_secs(1);
        loop {
            let e = match twitch::alerts(ctx_fut.clone()).await {
                Ok(never) => match never {},
                Err(e) => e,
            };
            if last_crash.elapsed() >= Duration::from_secs(60 * 60 * 24) {
                wait_time = Duration::from_secs(1); // reset wait time after no crash for a day
            } else {
                wait_time *= 2; // exponential backoff
            }
            eprintln!("{}", e);
            if wait_time >= Duration::from_secs(if e.is_network_error() { 60 } else { 2 }) { // only notify on multiple consecutive errors
                notify_thread_crash(format!("Twitch"), Box::new(e), Some(wait_time)).await;
            }
            sleep(wait_time).await; // wait before attempting to reconnect
            last_crash = Instant::now();
        }
    })
    .task(|ctx_fut, notify_thread_crash| async move {
            match ipc::listen(ctx_fut, &notify_thread_crash).await {
                Ok(never) => match never {},
                Err(e) => {
                    eprintln!("{}", e);
                    notify_thread_crash(format!("IPC"), Box::new(e), None).await;
                }
            }
        })
    .task(|ctx_fut, _| async move {
        shutdown.await;
        serenity_utils::shut_down(&*ctx_fut.read().await).await;
    })
    .ok()
}
