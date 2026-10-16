/*
 * syscall_demo.c  -  real Linux system calls: fork, exec, wait, pipe, write, read
 *
 * Run on Linux or Windows WSL:
 *      gcc syscall_demo.c -o syscall_demo
 *      ./syscall_demo
 *
 * The story: the lab "server" (parent) starts a "student program" (child),
 * sends it a message through a pipe, and waits until it finishes.
 */

#include <stdio.h>      /* printf                          */
#include <stdlib.h>     /* exit                            */
#include <unistd.h>     /* fork, pipe, read, write, close, getpid, execlp */
#include <sys/wait.h>   /* wait                            */
#include <string.h>     /* strlen                          */

int main(void)
{
    int pipe_fd[2];          /* pipe_fd[0] = read end, pipe_fd[1] = write end */
    pid_t child_pid;         /* will hold the id that fork() gives back       */

    /* STEP 1: pipe() makes a one-way channel and gives us two file descriptors. */
    if (pipe(pipe_fd) == -1) {
        perror("pipe failed");
        exit(1);
    }

    printf("[parent %d] starting a student program...\n", getpid());
    fflush(stdout);          /* printf keeps text in a buffer. Flush it BEFORE fork(),
                                otherwise the child gets a copy and prints it twice. */

    /* STEP 2: fork() copies this process.
     *   In the PARENT it returns the child's pid (a number > 0).
     *   In the CHILD  it returns 0.
     *   On error      it returns -1.                                           */
    child_pid = fork();

    if (child_pid == -1) {
        perror("fork failed");
        exit(1);
    }

    if (child_pid == 0) {
        /* ---------------- CHILD PROCESS ---------------- */
        char buffer[100];
        int  bytes;

        close(pipe_fd[1]);   /* the child only reads, so close the write end */

        /* STEP 3: read() waits until the parent writes something. */
        bytes = read(pipe_fd[0], buffer, sizeof(buffer) - 1);
        buffer[bytes] = '\0';            /* end the text so printf can print it */
        printf("[child  %d] got message: \"%s\"\n", getpid(), buffer);
        fflush(stdout);                  /* exec() throws away unflushed buffers, so flush now */
        close(pipe_fd[0]);

        /* STEP 4: exec replaces this child with a brand-new program ("echo").
         * If exec works, the lines after it never run.                       */
        execlp("echo", "echo", "[child] running the student program (echo)", (char *)NULL);

        perror("exec failed");           /* only reached if exec failed */
        exit(1);
    }

    /* ---------------- PARENT PROCESS ---------------- */
    const char *message = "start lab task";

    close(pipe_fd[0]);                                   /* the parent only writes */
    write(pipe_fd[1], message, strlen(message));         /* STEP 5: write() into the pipe */
    close(pipe_fd[1]);                                   /* closing tells the reader "no more data" */

    /* STEP 6: wait() pauses the parent until the child ends and returns its pid.
     * Without wait() a finished child stays as a "zombie" in the process table. */
    int status;
    wait(&status);

    if (WIFEXITED(status)) {
        printf("[parent %d] child %d finished with exit code %d\n",
               getpid(), child_pid, WEXITSTATUS(status));
    }
    return 0;
}
