package org.shen.flowcontrol;

import java.util.Random;
import java.util.Scanner;

public class GuessNumber {

    private static int TOTAL_ALLOWED = 10;
    private static int LIMIT = 100;

    enum Command {
        Stop,
        More
    }

    public static void main(String[] argus) {
        Random rand = new Random();
        Scanner scan = new Scanner(System.in);

        GuessNumber game = new GuessNumber();

        int score = 0;
        Command cmd = Command.More;
        while (cmd == Command.More) {
            score += game.runGuess(rand, scan);

            System.out.println("Your total score is " + score);
            System.out.println("Do you want to continue?(yes/no)");
            do {
                String input = scan.nextLine().toLowerCase();
                if (input.startsWith("yes")) {
                    cmd = Command.More;
                    break;
                }
                else if (input.startsWith("no")) {
                    cmd = Command.Stop;
                    break;
                }
            }
            while(true);
        }
    }

    public int runGuess(Random rand, Scanner scan) {
        int tries = 0;
        int target = rand.nextInt(LIMIT);
        while (tries++ < TOTAL_ALLOWED) {
            int number = getNumber(scan);
            if (number == target) {
                System.out.println("Bingo, you win!");
                return TOTAL_ALLOWED - tries;
            }
            else if (number < target) {
                System.out.println("Your guess is too small, try again!");
            }
            else {
                System.out.println("Your guess is too big, try again!");
            }
        }
        System.out.println("You tried too many times!");
        return -1;
    }

    private int getNumber(Scanner scan) {
        System.out.println("Enter a Number");
        return scan.nextInt();
    }
}
