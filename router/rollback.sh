#!/bin/sh
# Convenience wrapper for an installed router.  Use a snapshot directory
# produced by /usr/bin/campus-route snapshot.
exec /usr/bin/campus-route-rollback "$@"