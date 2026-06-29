#include <stdlib.h>
#include <unistd.h>
#include <libgen.h>
#include <mach-o/dyld.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <spawn.h>
#include <sys/wait.h>

extern char **environ;

/* Native launcher: stays alive as the parent while python runs as its child.
   This way macOS attaches the permissions (Accessibility / Screen Recording)
   to the app itself, not to the interpreter (zsh/python). */
int main(void) {
    char exe[PATH_MAX];
    uint32_t size = sizeof(exe);
    if (_NSGetExecutablePath(exe, &size) != 0) return 1;
    char dir[PATH_MAX];
    strncpy(dir, exe, sizeof(dir));
    dir[sizeof(dir) - 1] = '\0';
    char res[PATH_MAX];
    snprintf(res, sizeof(res), "%s/../Resources", dirname(dir));
    if (chdir(res) != 0) return 1;

    /* -B: do not write .pyc cache into the bundle, so the app signature stays intact */
    char *args[] = {"/usr/bin/python3", "-B", "crossy_gui.py", NULL};
    pid_t pid;
    if (posix_spawn(&pid, "/usr/bin/python3", NULL, NULL, args, environ) != 0)
        return 1;
    int status;
    waitpid(pid, &status, 0);
    return 0;
}
