# import sys
# import re
# from utils import Utilities

# class Analyzer(object):
#     def __init__(self, group):
#         self.group = group
#         self.display = (self.group == "id")

#         # Load the positive and negative words
#         self.words = {}
#         with open("words/positive.txt") as file:
#             for line in file:
#                 self.words[line.rstrip()] = 1
#         with open("words/negative.txt") as file:
#             for line in file:
#                 self.words[line.rstrip()] = -1

#     def analyze(self, message):
#         score = 0
#         found = 0
#         disp = ""

#         i = 0
#         parts = Utilities.split(message)
#         for w in parts:
#             if w in self.words:
#                 score += self.words[w]
#                 found += 1
#                 if self.display:
#                     i = message.lower().find(w, i)
#                     d = Utilities.get_colored_text(self.words[w], message[i:i+len(w)])
#                     message = message[:i] + d + message[i+len(w):]
#                     i = i + len(d)

#                     disp += d + " "

#         label = score / float(found) if found != 0 else 0.0
#         return (label, disp, message)

#     def output(self, group, message, label, disp):
#         g = "{}\t".format(group) if self.group != "score" else ""

#         text = ""
#         if self.display:
#             text = "\t{}| {}".format(disp, message.replace('\n',' '))

#         print("{}{:.2f}{}".format(g, label, text))

# def main(argv):
#     group = argv[0] if len(argv) > 0 else "id"
#     analyzer = Analyzer(group)
#     for data in Utilities.read_json(sys.stdin, group=group):
#         (label, disp, message) = analyzer.analyze(data["message"])
#         group = data["group"] if "group" in data else ""
#         analyzer.output(group, message, label, disp)

# if __name__ == "__main__":
#     main(sys.argv[1:])


import sys
from utils import Utilities

class Analyzer(object):
    def __init__(self, group):
        self.group = group
        self.display = (self.group == "id")

        # Load the positive and negative words
        self.words = {}
        with open("words/positive.txt") as file:
            for line in file:
                self.words[line.rstrip()] = 1
        with open("words/negative.txt") as file:
            for line in file:
                self.words[line.rstrip()] = -1

    def analyze(self, message):
        score = 0
        found = 0
        disp = ""

        parts = Utilities.split(message)
        for w in parts:
            if w in self.words:
                score += self.words[w]
                found += 1
                if self.display:
                    disp += w + " "

        label = score / float(found) if found != 0 else 0.0
        return (label, disp, message)

    def output(self, group, message, label, disp):
        g = "{}\t".format(group) if self.group != "score" else ""
        text = ""
        if self.display:
            text = "\t{}| {}".format(disp, message.replace('\n', ' '))  # Replace newline characters with spaces

        print("{}{:.2f}{}".format(g, label, text))

# def main(argv):
#     group = argv[0] if len(argv) > 0 else "id"
#     analyzer = Analyzer(group)
#     for data in Utilities.read_json(sys.stdin, group=group):
#         for commit in data["payload"]["commits"]:
#             message = commit["message"]
#             (label, disp, _) = analyzer.analyze(message)
#             analyzer.output(data["id"], message, label, disp)

import json

def main(argv):
    group = argv[0] if len(argv) > 0 else "id"
    analyzer = Analyzer(group)

    # Read the input file line by line
    for line in sys.stdin:
        try:
            data = json.loads(line)
            process_item(analyzer, group, data)
        except ValueError as e:
            print(f"Error parsing JSON data: {e}")
            continue

def process_item(analyzer, group, item):
    if "payload" in item and "commits" in item["payload"]:
        for commit in item["payload"]["commits"]:
            message = commit["message"]
            (label, disp, _) = analyzer.analyze(message)
            analyzer.output(item["id"], message, label, disp)



if __name__ == "__main__":
    main(sys.argv[1:])
