//! Implements auto-moderating games of Werewolf.

#![allow(missing_docs)]

use {
    std::{
        cmp::Ordering,
        collections::{
            HashMap,
            HashSet,
        },
        iter,
        mem,
        pin::Pin,
        str,
        time::Duration,
    },
    futures::{
        future::Future,
        stream::{
            self,
            StreamExt as _,
            TryStreamExt as _,
        },
    },
    itertools::Itertools as _,
    quantum_werewolf::game::{
        NightAction,
        NightActionResult,
        Role,
        state::*,
    },
    rand::{
        prelude::*,
        rng,
    },
    serde::{
        Deserialize,
        Serialize,
    },
    serenity::{
        all::EditMember,
        model::prelude::*,
        prelude::*,
        utils::MessageBuilder,
    },
    tokio::time::sleep,
    super::{
        Error,
        lang::*,
        parse,
    },
};
pub use quantum_werewolf::game::state::State;

#[derive(Debug, Deserialize, Serialize, Clone, Copy)]
#[serde(rename_all = "camelCase")]
pub struct Config {
    pub role: RoleId,
    pub text_channel: ChannelId,
    pub voice_channel: Option<ChannelId>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Vote {
    Player(UserId),
    NoLynch,
}

#[derive(Debug)]
pub enum Action {
    Night(NightAction<UserId>),
    Vote(UserId, Vote),
    Unvote(UserId),
}

impl Action {
    pub fn src(&self) -> UserId {
        match *self {
            Action::Night(ref a) => *a.src(),
            Action::Vote(src, _) | Action::Unvote(src) => src,
        }
    }
}

/// The global game state is tracked here. Also serves as `typemap` key for the global game.
#[derive(Debug)]
pub struct GameState {
    guild: GuildId,
    config: Config,
    pub state: State<UserId>,
    alive: Option<HashSet<UserId>>,
    night_actions: Vec<NightAction<UserId>>,
    timeouts: Vec<bool>,
    votes: HashMap<UserId, Vote>,
}

impl GameState {
    pub fn new(guild: GuildId, config: Config) -> GameState {
        GameState {
            guild, config,
            state: State::default(),
            alive: None,
            night_actions: Vec::default(),
            timeouts: Vec::default(),
            votes: HashMap::default(),
        }
    }

    async fn announce_deaths(&mut self, ctx: &Context, new_alive: Option<HashSet<UserId>>) -> Result<(), Error> {
        self.alive = if let Some(new_alive) = new_alive {
            let new_alive = new_alive.iter().cloned().collect();
            if let Some(ref old_alive) = self.alive {
                let mut died = stream::iter(old_alive - &new_alive).then(|user_id| user_id.to_user(ctx)).try_collect::<Vec<_>>().await?;
                if !died.is_empty() {
                    died.sort_by_key(|user| (user.name.clone(), user.discriminator));
                    let mut builder = MessageBuilder::default();
                    for (i, dead_player) in died.into_iter().enumerate() {
                        // update permissions
                        let roles = self.guild.member(ctx, dead_player.clone()).await?.roles.into_iter().filter(|&role| role != self.config.role);
                        self.guild.edit_member(ctx, dead_player.clone(), EditMember::default().roles(roles)).await?;
                        // add to announcement
                        if i > 0 {
                            builder.push(" ");
                        }
                        builder.mention(&dead_player);
                        builder.push(" ist tot");
                        if let Some(role) = self.state.role(&dead_player.id) {
                            builder.push(" und war ");
                            builder.push_safe(role_name(role, Nom, false));
                        }
                        builder.push(".");
                    }
                    self.config.text_channel.say(ctx, builder.build()).await?;
                }
            }
            Some(new_alive)
        } else {
            None
        };
        //TODO send new role DMs for remaining Quantum States
        Ok(())
    }

    fn cancel_all_timeouts(&mut self) {
        self.timeouts = vec![false; self.timeouts.len()];
    }

    fn cancel_timeout(&mut self, timeout_idx: usize) {
        self.timeouts[timeout_idx] = false;
    }

    async fn resolve_day(&mut self, ctx: &Context, day: Day<UserId>) -> Result<(), Error> {
        self.cancel_all_timeouts();
        // close discussion
        self.config.text_channel.delete_permission(ctx, PermissionOverwriteType::Role(self.config.role)).await?;
        self.config.text_channel.say(ctx, "Die Diskussion ist geschlossen.").await?;
        // determine the players and/or game actions with the most votes
        let (_, vote_result) = vote_leads(&self);
        // if the result is a single player, lynch that player
        self.state = if vote_result.len() == 1 {
            match vote_result.into_iter().next().unwrap() {
                Vote::Player(user_id) => day.lynch(user_id),
                Vote::NoLynch => day.no_lynch(),
            }
        } else {
            day.no_lynch()
        };
        self.votes = HashMap::default();
        let new_alive = self.state.alive().map(|new_alive| new_alive.into_iter().cloned().collect());
        self.announce_deaths(ctx, new_alive).await?;
        if let State::Night(ref night) = self.state {
            self.start_night(ctx, night).await?;
        }
        Ok(())
    }

    async fn resolve_night(&mut self, ctx: &Context, night: Night<UserId>) -> Result<State<UserId>, Error> {
        self.cancel_all_timeouts();
        let result = night.resolve_nar(&self.night_actions);
        self.night_actions = Vec::default();
        if let State::Day(ref day) = result {
            // send night action results
            for (player, result) in day.night_action_results() {
                match result {
                    NightActionResult::Investigation(target, faction) => {
                        let dm = MessageBuilder::default()
                            .push("Ergebnis deiner Nachtaktion: ")
                            .dm_mention(&target.to_user(ctx).await?)
                            .push(" gehört ")
                            .push_safe(zu(faction_gender(faction)))
                            .push(" ")
                            .push_safe(faction_name(faction, Dat))
                            .build();
                        player.create_dm_channel(ctx).await?.say(ctx, &dm).await?;
                    }
                }
            }
            self.start_day(ctx, day).await?;
        }
        Ok(result)
    }

    async fn start_day(&self, ctx: &Context, day: &Day<UserId>) -> Result<(), Error> {
        // announce probability table
        let mut builder = MessageBuilder::default();
        builder.push("Die aktuelle Wahrscheinlichkeitsverteilung:");
        for (player_idx, probabilities) in day.probability_table().into_iter().enumerate() {
            builder.push_line("").push_safe(match probabilities {
                Ok((village_ratio, werewolves_ratio, dead_ratio)) => {
                    format!("{}: {}% Dorf, {}% Werwolf, {}% tot", player_idx + 1, (village_ratio * 100.0).round() as u8, (werewolves_ratio * 100.0).round() as u8, (dead_ratio * 100.0).round() as u8)
                }
                Err(faction) => {
                    format!("{}: tot (war {})", player_idx + 1, faction_name_sg(faction, Nom))
                }
            });
        }
        self.config.text_channel.say(ctx, builder.build()).await?;
        // open discussion
        self.config.text_channel.create_permission(ctx, PermissionOverwrite {
            kind: PermissionOverwriteType::Role(self.config.role),
            allow: Permissions::SEND_MESSAGES | Permissions::ADD_REACTIONS,
            deny: Permissions::empty(),
        }).await?;
        let lynch_votes = day.alive().len() / 2 + 1;
        let mut builder = MessageBuilder::default();
        builder.push("Es wird Tag. Die Diskussion ist eröffnet. Absolute Mehrheit besteht aus ");
        builder.push_safe(cardinal(lynch_votes, Dat, F));
        builder.push(if lynch_votes == 1 { " Stimme." } else { " Stimmen." });
        self.config.text_channel.say(ctx, builder.build()).await?;
        Ok(())
    }

    async fn start_night(&self, ctx: &Context, _: &Night<UserId>) -> Result<(), Error> {
        self.config.text_channel.say(ctx, "Es wird Nacht. Bitte schickt mir innerhalb der nächsten 3 Minuten eure Nachtaktionen.").await?; //TODO adjust for night timeout changes
        Ok(())
    }

    fn start_timeout(&mut self) -> usize {
        let idx = self.timeouts.len();
        self.timeouts.push(true);
        idx
    }

    fn timeout_cancelled(&self, timeout_idx: usize) -> bool {
        !self.timeouts[timeout_idx]
    }

    fn timeouts_active(&self) -> bool {
        self.timeouts.iter().any(|&active| active)
    }
}

impl TypeMapKey for GameState {
    type Value = HashMap<GuildId, GameState>;
}

pub async fn channel_check(ctx: &Context, interaction: &CommandInteraction) -> Result<GuildId, &'static str> {
    if let Some(guild_id) = interaction.guild_id {
        if let Some(conf) = ctx.data.read().await.get::<crate::config::Config>().expect("missing config").discord.werewolf.get(&guild_id) {
            if interaction.channel_id == conf.text_channel {
                Ok(guild_id)
            } else {
                Err("Dieser Befehl funktioniert nur im Werwölfe-Channel.")
            }
        } else {
            Err("Werwölfe ist auf diesem Server noch nicht eingerichtet.")
        }
    } else {
        Err("Dieser Befehl funktioniert nur in einem Channel.")
    }
}

pub async fn continue_game(ctx: &Context, guild: GuildId) -> Result<(), Error> {
    let (mut timeout_idx, mut sleep_duration) = {
        let mut data = ctx.data.write().await;
        let state_ref = data.get_mut::<GameState>().expect("missing Werewolf game state").get_mut(&guild).expect("tried to continue game that hasn't started");
        if let Some(duration) = handle_game_state(ctx, state_ref).await? {
            if state_ref.timeouts_active() { return Ok(()) }
            (state_ref.start_timeout(), duration)
        } else {
            return Ok(())
        }
    };
    loop {
        sleep(sleep_duration).await;
        let mut data = ctx.data.write().await;
        let state_ref = data.get_mut::<GameState>().expect("missing Werewolf game state").get_mut(&guild).expect("tried to continue game that hasn't started");
        if state_ref.timeout_cancelled(timeout_idx) { break }
        state_ref.cancel_timeout(timeout_idx);
        if let Some(duration) = handle_timeout(ctx, state_ref).await? {
            if state_ref.timeouts_active() { break }
            timeout_idx = state_ref.start_timeout();
            sleep_duration = duration;
        } else {
            break
        }
    }
    Ok(())
}

/// Processes an action.
///
/// If the action was valid, returns `Ok`.
///
/// A return value of `Error::GameAction` indicates an invalid action. Other return values are internal errors.
pub async fn handle_action(ctx: &Context, msg: &Message, action: Action) -> Result<(), Error> {
    let guild = {
        let mut data = ctx.data.write().await;
        let (guild, state_ref) = data
            .get_mut::<GameState>()
            .expect("missing Werewolf game state")
            .iter_mut()
            .filter(|(_, state)| state.state.secret_ids().map_or(false, |secret_ids| secret_ids.contains(&action.src())))
            .exactly_one()
            .map_err(|_| Error::GameAction("du spielst nicht mit oder bist in mehreren Spielen gleichzeitig".into()))?;
        match state_ref.state {
            State::Night(ref night) => {
                match action {
                    Action::Night(night_action) => {
                        if !night.secret_ids().contains(night_action.src()) { return Err(Error::GameAction("du spielst nicht mit".into())) }
                        state_ref.night_actions.push(night_action);
                    }
                    Action::Vote(_, _) | Action::Unvote(_) => return Err(Error::GameAction("aktuell läuft keine Abstimmung".into())),
                }
            }
            State::Day(ref day) => match action {
                Action::Vote(src_id, vote) => {
                    if !day.alive().contains(&src_id) { return Err(Error::GameAction("tote Spieler können nicht abstimmen".into())) }
                    state_ref.votes.insert(src_id, vote);
                }
                Action::Unvote(src_id) => {
                    if !day.alive().contains(&src_id) { return Err(Error::GameAction("tote Spieler können nicht abstimmen".into())) }
                    state_ref.votes.remove(&src_id);
                }
                Action::Night(_) => return Err(Error::GameAction("es ist Tag".into())),
            }
            State::Signups(_) | State::Complete(_) => return Err(Error::GameAction("aktuell läuft kein Spiel".into())),
        }
        *guild
    };
    msg.react(ctx, '👀').await?;
    continue_game(ctx, guild).await?;
    Ok(())
}

fn handle_game_state<'a>(ctx: &'a Context, state_ref: &'a mut GameState) -> Pin<Box<dyn Future<Output = Result<Option<Duration>, Error>> + Send + 'a>> {
    Box::pin(async move {
        let new_alive = { state_ref.state.alive().map(|new_alive| new_alive.into_iter().cloned().collect()) };
        state_ref.announce_deaths(ctx, new_alive).await?;
        let state = mem::replace(&mut state_ref.state, State::default());
        Ok(match state {
            State::Signups(signups) => {
                if signups.num_players() < MIN_PLAYERS {
                    state_ref.state = State::Signups(signups);
                    None
                } else {
                    if !state_ref.timeouts_active() {
                        state_ref.config.text_channel.say(ctx, "das Spiel startet in einer Minute").await?;
                    }
                    state_ref.state = State::Signups(signups);
                    Some(Duration::from_secs(60)) // allow more players to sign up
                }
            }
            State::Night(night) => {
                if night.actions_complete(&state_ref.night_actions) {
                    state_ref.state = state_ref.resolve_night(ctx, night).await?;
                    handle_game_state(ctx, state_ref).await?
                } else {
                    state_ref.state = State::Night(night);
                    Some(Duration::from_secs(180)) // 3 minute night time limit works for XylBot, may need to be adjusted up or down. Collect stats?
                }
            }
            State::Day(day) => {
                let (max_votes, vote_result) = vote_leads(&state_ref);
                if max_votes > day.alive().len() / 2 && vote_result.len() == 1 {
                    state_ref.resolve_day(ctx, day).await?;
                    handle_game_state(ctx, state_ref).await?
                } else {
                    state_ref.state = State::Day(day);
                    Some(Duration::from_secs(1800)) // Not sure how long the day limit should be. Starting out with half an hour for now to be safe. Collect stats?
                }
            }
            State::Complete(Complete { winners }) => {
                let mut winners = stream::iter(winners).then(|user_id| user_id.to_user(ctx)).try_collect::<Vec<_>>().await?;
                winners.sort_by_key(|user| (user.name.clone(), user.discriminator));
                let mut builder = MessageBuilder::default();
                builder.push("das Spiel ist vorbei: ");
                state_ref.config.text_channel.say(ctx, match winners.len() {
                    0 => builder.push("niemand hat gewonnen"),
                    1 => builder.mention(&winners.swap_remove(0)).push(" hat gewonnen"),
                    _ => {
                        builder.mention(&winners.remove(0));
                        for winner in winners {
                            builder.push(" ").mention(&winner);
                        }
                        builder.push(" haben gewonnen")
                    }
                }.build()).await?;
                // unlock channel
                state_ref.config.text_channel.delete_permission(ctx, PermissionOverwriteType::Role(state_ref.guild.everyone_role())).await?;
                for member in state_ref.guild.members(ctx, None, None).await? { //TODO make sure all members are checked
                    if member.roles(ctx).map_or(false, |roles| roles.into_iter().any(|role| role.id == state_ref.config.role)) {
                        member.remove_role(ctx, state_ref.config.role).await?;
                    }
                }
                state_ref.state = State::default();
                None
            }
        })
    })
}

async fn handle_timeout(ctx: &Context, state_ref: &mut GameState) -> Result<Option<Duration>, Error> {
    let state = mem::replace(&mut state_ref.state, State::default());
    state_ref.state = match state {
        State::Signups(signups) => {
            if signups.num_players() < MIN_PLAYERS {
                State::Signups(signups)
            } else {
                // lock channel
                state_ref.config.text_channel.create_permission(ctx, PermissionOverwrite {
                    kind: PermissionOverwriteType::Role(state_ref.guild.everyone_role()),
                    allow: Permissions::empty(),
                    deny: Permissions::SEND_MESSAGES | Permissions::ADD_REACTIONS
                }).await?;
                // create a random role distribution
                let num_ww = signups.num_players() * 2 / 5;
                let mut roles = (0..num_ww).map(|i| Role::Werewolf(i)).collect::<Vec<_>>();
                roles.push(Role::Detective);
                if signups.num_players() > 4 && rng().random() { roles.push(Role::Healer); }
                // start the game with that distribution
                let started = signups.start(roles.clone())?;
                for (secret_id, player) in started.secret_ids().expect("failed to get secred player IDs").into_iter().enumerate() {
                    let dm = quantum_role_dm(&roles, started.num_players(), secret_id);
                    player.create_dm_channel(ctx).await?.say(ctx, &dm).await?;
                }
                match started {
                    State::Night(ref night) => {
                        state_ref.start_night(ctx, night).await?;
                    }
                    State::Day(ref day) => {
                        state_ref.start_day(ctx, day).await?;
                    }
                    _ => ()
                }
                started
            }
        }
        State::Night(night) => state_ref.resolve_night(ctx, night).await?,
        State::Day(day) => {
            state_ref.resolve_day(ctx, day).await?;
            mem::replace(&mut state_ref.state, State::default())
        }
        State::Complete(_) => unimplemented!(), // there shouldn't be any timeouts after the game ends
    };
    handle_game_state(ctx, state_ref).await
}

pub async fn parse_action(ctx: &Context, src: UserId, mut msg: &str) -> Option<Result<Action, Error>> {
    async fn parse_player(ctx: &Context, guild: GuildId, subj: &mut &str) -> Result<UserId, Option<UserId>> {
        if let Some(user_id) = parse::eat_user_mention(subj) {
            if player_in_game(ctx, user_id, guild).await { Ok(user_id) } else { Err(Some(user_id)) }
        } else {
            let data = ctx.data.read().await;
            let state_ref = data.get::<GameState>().expect("missing Werewolf game state").get(&guild).expect("tried to parse action for missing game");
            if let Some(user_ids) = state_ref.state.secret_ids() {
                if let Some(next_word) = parse::next_word(&subj) {
                    let users = if let Ok(users) = stream::iter(user_ids).then(|user_id| user_id.to_user(ctx)).try_collect::<Vec<_>>().await { users } else { return Err(None) };
                    let matching_users = user_ids.into_iter().zip(users).filter_map(|(&user_id, user)| if user.name == next_word { Some(user_id) } else { None }).collect::<Vec<_>>();
                    if matching_users.len() == 1 {
                        *subj = &subj[next_word.len()..]; // consume username
                        return Ok(matching_users[0])
                    }
                    //TODO parse `username#1234` or `@user name#1234` syntax
                }
            }
            Err(None)
        }
    }

    // A simple parser for game actions.
    let guild = *ctx.data.read().await.get::<GameState>().expect("missing Werewolf game state").iter().filter(|(_, state)| state.state.secret_ids().map_or(false, |secret_ids| secret_ids.contains(&src))).map(|(guild_id, _)| guild_id).exactly_one().ok()?;
    if msg.starts_with('!') { msg = &msg[1..] } // remove leading `!`, if any
    let cmd_name = if let Some(cmd_name) = parse::next_word(&msg) { cmd_name } else { return None };
    msg = &msg[cmd_name.len()..]; // consume command name
    parse::eat_whitespace(&mut msg);
    Some(match &cmd_name[..] {
        "h" | "heal" => {
            match parse_player(ctx, guild, &mut msg).await {
                Ok(tgt) => Ok(Action::Night(NightAction::Heal(src, tgt))),
                Err(Some(user_id)) => Err(Error::GameAction(MessageBuilder::default().mention(&user_id).push(" spielt nicht mit").build())), //TODO use dm_mention if in DM channel
                Err(None) => Err(Error::GameAction("kann das Ziel nicht lesen".into()))
            }
        }
        "i" | "inspect" | "investigate" => {
            match parse_player(ctx, guild, &mut msg).await {
                Ok(tgt) => Ok(Action::Night(NightAction::Investigate(src, tgt))),
                Err(Some(user_id)) => Err(Error::GameAction(MessageBuilder::default().mention(&user_id).push(" spielt nicht mit").build())), //TODO use dm_mention if in DM channel
                Err(None) => Err(Error::GameAction("kann das Ziel nicht lesen".into()))
            }
        }
        "k" | "kill" => {
            match parse_player(ctx, guild, &mut msg).await {
                Ok(tgt) => Ok(Action::Night(NightAction::Kill(src, tgt))),
                Err(Some(user_id)) => Err(Error::GameAction(MessageBuilder::default().mention(&user_id).push(" spielt nicht mit").build())), //TODO use dm_mention if in DM channel
                Err(None) => Err(Error::GameAction("kann das Ziel nicht lesen".into()))
            }
        }
        "sleep" => unimplemented!(), //TODO if *this player's* mandatory night actions are complete, note that the player is done submitting night actions. otherwise, reply with an error
        "unvote" => Ok(Action::Unvote(src)),
        "v" | "vote" => {
            if msg.is_empty() {
                Ok(Action::Unvote(src))
            } else {
                if vec!["no lynch", "nolynch", "nl"].into_iter().any(|prefix| msg.to_ascii_lowercase() == prefix) {
                    return Some(Ok(Action::Vote(src, Vote::NoLynch)))
                }
                match parse_player(ctx, guild, &mut msg).await {
                    Ok(tgt) => Ok(Action::Vote(src, Vote::Player(tgt))),
                    Err(Some(user_id)) => Err(Error::GameAction(MessageBuilder::default().mention(&user_id).push(" spielt nicht mit").build())), //TODO use dm_mention if in DM channel
                    Err(None) => Err(Error::GameAction("kann das Ziel nicht lesen".into()))
                }
            }
        }
        _ => { return None }
    })
}

pub async fn player_in_game(ctx: &Context, user_id: UserId, guild_id: GuildId) -> bool {
    let data = ctx.data.read().await;
    let state_ref = data.get::<GameState>().expect("missing Werewolf game state").get(&guild_id);
    state_ref.map_or(false, |state_ref| state_ref.state.secret_ids().map_or(false, |secret_ids| secret_ids.contains(&user_id)))
}

pub fn quantum_role_dm(roles: &[Role], num_players: usize, secret_id: usize) -> String {
    // Willkommen
    let mut builder = MessageBuilder::default();
    builder.push_line("Willkommen bei Quantenwerwölfe!"); //TODO Spielname (flavor) oder Variantenname (für normales ww etc)
    // Rollenname
    let mut role_counts = HashMap::<_, usize>::default();
    let extra_villagers = num_players - roles.len();
    if extra_villagers > 0 {
        role_counts.insert(Role::Villager, extra_villagers);
    }
    for &role in roles {
        let normalized_role = if let Role::Werewolf(_) = role {
            Role::Werewolf(0)
        } else {
            role
        };
        *role_counts.entry(normalized_role).or_insert(0) += 1;
    }
    let mut role_count_list = role_counts.clone().into_iter().collect::<Vec<_>>();
    role_count_list.sort_by_key(|&(role, _)| role_name(role, Nom, false));
    builder.push("Du bist eine ");
    builder.push_bold_safe(format!("Quantenüberlagerung aus {}", join(None, role_count_list.into_iter().map(|(role, count)| {
        let card = cardinal(count as u64, Dat, role_gender(role));
        if let Role::Werewolf(_) = role {
            format!("{} {}", card, if count == 1 { "Werwolf" } else { "Werwölfen" })
        } else {
            format!("{} {}", card, role_name(role, Dat, count != 1))
        }
    }))));
    builder.push(".");
    // Rollenrang
    builder.push(" Dein Rollenrang ist ");
    builder.push_bold((secret_id + 1).to_string());
    builder.push(".");
    //TODO Partei (für qww erst relevant, wenn nur noch eine Rolle möglich ist)
    //TODO Dorfname (bei Variante „die Gemeinschaft der Dörfer“)
    builder.push_line("");
    //TODO Gruppenmitspieler (irrelevant für qww, zB Werwölfe, Freimaurer, Seherinnen/Kekse)
    // Aktionen (Parteiaktionen klar als solche kennzeichnen)
    if *role_counts.get(&Role::Healer).unwrap_or(&0) > 0 {
        builder.push("Solange du noch lebst, kannst du jede Nacht einen lebenden Spieler deiner Wahl heilen (");
        builder.push_mono_safe("heal <player>");
        builder.push_line("). In allen Universen, in denen du lebst und Heiler bist, kann dieser Spieler in dieser Nacht nicht sterben. Du kannst keinen Spieler heilen, den du schon in der vorherigen Nacht geheilt hast.");
    }
    if *role_counts.get(&Role::Detective).unwrap_or(&0) > 0 {
        builder.push("Solange du noch lebst, kannst du jede Nacht einen Spieler deiner Wahl untersuchen (");
        builder.push_mono_safe("investigate <player>");
        builder.push_line("). Falls es mindestens ein Universum gibt, in dem du Detektiv bist, erfährst du die Partei dieses Spielers in einem zufälligen solchen Universum. Alle Universen, in denen du Detektiv bist und der Spieler nicht diese Partei hat, werden eliminiert.");
    }
    builder.push("Solange du noch lebst, tötest du in jeder Nacht einen lebenden Spieler deiner Wahl (");
    builder.push_mono_safe("kill <player>");
    builder.push_line("). In allen Universen, in denen du der Werwolf mit der kleinsten Rangnummer unter den lebenden Werwölfen bist, stirbt dieser Spieler.");
    // sonstige Effekte (Parteieffekte klar als solche kennzeichnen)
    builder.push_line("Jeden Morgen wird öffentlich aber anonym dein Rollenrang sowie die relativen Häufigkeiten der Universen, in denen du zum Dorf gehörst, derer in denen du zu den Werwölfen gehörst, und derer in denen du tot bist angekündigt.");
    builder.push_line("Wenn du in allen Universen tot bist, stirbst du.");
    builder.push_line("Wenn du stirbst oder am Ende des Spiels wird aus den Universen, in denen du bis eben noch gelebt hast, ein zufälliges ausgewählt und du bekommst deine Identität aus diesem Universum. Alle anderen Quantenüberlagerungen verlieren diese Identität aus ihren Überlagerungen, und alle Universen, in denen du nicht diese Identität warst, werden eliminiert.");
    //TODO wincons (für qww erst relevant, wenn nur noch eine Rolle möglich ist)
    //TODO optional: Kurzzusammenfassung der Regeln bzw link zu den vollständigen Regeln
    // Unterschrift
    builder.push("Viel Spaß!");
    builder.build()
}

fn vote_leads(state_ref: &GameState) -> (usize, HashSet<Vote>) {
    let mut vote_count = HashMap::<Vote, usize>::default();
    for (_, &vote) in state_ref.votes.iter() {
        *vote_count.entry(vote).or_insert(0) += 1;
    }
    vote_count.into_iter()
        .fold((0, HashSet::default()), |(max_votes, mut voted), (vote, count)|
            match count.cmp(&max_votes) {
                Ordering::Less => (max_votes, voted),
                Ordering::Equal => {
                    voted.insert(vote);
                    (max_votes, voted)
                }
                Ordering::Greater => (count, iter::once(vote).collect()),
            }
        )
}
