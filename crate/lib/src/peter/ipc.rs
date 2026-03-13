use {
    std::iter,
    serenity::{
        all::EditMember,
        prelude::*,
    },
    super::GEFOLGE,
};

serenity_utils::ipc! {
    use serenity::model::prelude::*;

    const PORT: u16 = 18807;

    /// Creates a permission override for a given channel and user, allowing them to view the channel and send messages.
    async fn add_channel_access(ctx: &Context, channel: ChannelId, user: UserId) -> Result<(), String> {
        channel.create_permission(ctx, PermissionOverwrite {
            allow: Permissions::VIEW_CHANNEL | Permissions::SEND_MESSAGES,
            deny: Permissions::default(),
            kind: PermissionOverwriteType::Member(user),
        }).await.map_err(|e| format!("failed to create permission overwrite: {e}"))?;
        Ok(())
    }

    /// Adds the given role to the given user. No-op if the user already has the role.
    async fn add_role(ctx: &Context, user: UserId, role: RoleId) -> Result<(), String> {
        let roles = iter::once(role).chain(GEFOLGE.member(ctx, user).await.map_err(|e| format!("failed to get member data: {e}"))?.roles.into_iter());
        GEFOLGE.edit_member(ctx, user, EditMember::default().roles(roles)).await.map_err(|e| format!("failed to edit roles: {e}"))?;
        Ok(())
    }

    /// Sends the given message, unescaped, to the given channel.
    async fn channel_msg(ctx: &Context, channel: ChannelId, msg: String) -> Result<(), String> {
        channel.say(ctx, msg).await.map_err(|e| format!("failed to send channel message: {e}"))?;
        Ok(())
    }

    /// Sends the given message, unescaped, directly to the given user.
    async fn msg(ctx: &Context, rcpt: UserId, msg: String) -> Result<(), String> {
        rcpt.create_dm_channel(ctx).await
            .map_err(|e| format!("failed to get/create DM channel: {e}"))?
            .say(ctx, msg).await
            .map_err(|e| format!("failed to send DM: {e}"))?;
        Ok(())
    }

    /// Shuts down the bot and cleanly exits the program.
    async fn quit(ctx: &Context) -> Result<(), String> {
        serenity_utils::shut_down(&ctx).await;
        Ok(())
    }

    /// Changes the display name for the given user in the Gefolge guild to the given string.
    ///
    /// If the given string is equal to the user's username, the display name will instead be removed.
    async fn set_display_name(ctx: &Context, user_id: UserId, new_display_name: String) -> Result<(), String> {
        let user = user_id.to_user(ctx).await.map_err(|e| format!("failed to get user for set-display-name: {e}"))?;
        match GEFOLGE.edit_member(ctx, &user, EditMember::default().nickname(if user.name == new_display_name { "" } else { &new_display_name })).await {
            Ok(_) => Ok(()),
            Err(serenity::Error::Http(e)) => if let HttpError::UnsuccessfulRequest(response) = e {
                Err(format!("failed to set display name: {response:?}"))
            } else {
                Err(e.to_string())
            },
            Err(e) => Err(e.to_string()),
        }
    }
}
