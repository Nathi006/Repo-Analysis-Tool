University of the Witwatersrand                                                                     Overview                                                                               COMS3011A Test




                                                                     COMS3011A Test
                                                                                        Brendan Griffiths




Contents
1 Overview . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . ⁠1
2 Metrics . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . ⁠2
  2.1 File Metrics . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . ⁠3
  2.2 Directory Metrics . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . ⁠3
  2.3 Repository Metrics . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . ⁠4
  2.4 Commit set Metrics . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . ⁠4
  2.5 Author Metrics . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . ⁠5
3 Rubric . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . ⁠5



1 Overview
Time: 2.5 Hours
Submission: URL to a public repository
Git repositories tend to be very opaque to understanding. Git does not make it easy to understand how a
repo has evolved, who has had the most impact where, and what parts of the project are the most
volatile.
Your project manager has asked you to build a Repo Analysis Tool (RAT) that measures specific metrics
of a provided repository. You need to calculate these metrics for: each developer (called an author), each
file, each directory, and the entire repository. These metrics are provided below.
The RAT should be a web-app dashboard for multiple repositories. This dashboard should be filterable
by:
• A repository
• An author
• A file or directory
• Commits
  ‣ a specified period of time
  ‣ or a manually selected list of commits
It accepts a repository in two forms:
1. A zip file of the repo with the .git file or directory
2. A remote repository URL that is then deeply cloned




                                                                                                        1/6
University of the Witwatersrand                    Metrics                                    COMS3011A Test




Not every commit will have the same author, even if they were made by the same person. To address
this git provides a .mailmap to merge different email addresses, the RAT should be able to merge
authors using the mailmap. If no mailmap is provided, a user should still be able to merge different
authors manually.
The full list of features are:
• Repository Upload: Zip and Clone URL
• Multiple Repository Support
• Author Merging
• Metric Categories:
  ‣ File Metrics
  ‣ Directory Metrics
  ‣ Repository Metrics
  ‣ Commit Set Metrics
Note: Not all features are necessary. Please review the rubric to understand what is needed.



2 Metrics
A commit ℎ has the following properties
• A single author ℎ[𝑎] after author merging
• A previous commit ℎ[𝑝]
  ‣ The initial commit has ℎ[𝑝] = ℎ∅ , an empty commit
• A committer date ℎ[committer-date]
• ℎ[𝐹 ] is the set of all files
  ‣ Binary files are not measured
  ‣ Git provides a definition and detection of binary files
• ℎ[𝐷] is the set of all directories
• An object 𝑜 ∈ ℎ[𝐹 ] ∪ ℎ[𝐷] is identified by its path
  ‣ Rename detection is enabled with a threshold of 50%, so just renaming a file should not change its
    metrics.
    – Making a change and renaming an object should only have the changes impact its associated
       metrics.
    – These changes are attributed to its new path
  ‣ If an object is deleted (it does not exist in ℎ but does in ℎ[𝑝]), it should be recorded as a change in
    the necessary metrics (lines removed) on its path.
The set 𝐻̄ is the set of non-merge commits reachable from a specified reference commit ℎ𝑟 (typically
HEAD)
• A commit set 𝐻 is a subset of 𝐻̄
• The commit set 𝐻𝑡 is the commit history from UNIX timestamp 𝑡 to present

                                    𝐻𝑡 ≔ {ℎ ∈ 𝐻̄ | 𝑡 ≤ ℎ[committer-date]}
• The commit set 𝐻𝑖,𝑗 is the commit history from timestamp 𝑖 inclusive until timestamp 𝑗 exclusive

                                  𝐻𝑖,𝑗 ≔ {ℎ ∈ 𝐻̄ | 𝑖 ≤ ℎ[committer-date] < 𝑗}




                                                     2/6
University of the Witwatersrand                      Metrics                                     COMS3011A Test




• 𝐻[𝐹 ] is the set of all files in the repository

                                          𝐻[𝐹 ] ≔ ⋃ (ℎ[𝐹 ] ∪ ℎ[𝑝][𝐹 ])
                                                    ℎ∈𝐻
• 𝐻[𝐷] is the set of all directories (including the root) for the commit set.

                                          𝐻[𝐷] ≔ ⋃ (ℎ[𝐷] ∪ ℎ[𝑝][𝐷])
                                                    ℎ∈𝐻




2.1 File Metrics
• File Added Lines: The number of lines added on file 𝑓 from a commit ℎ to the previous commit

                                                          𝑙+
                                                           ℎ,𝑓

• File Removed Lines: The number of lines removed on file 𝑓 from a commit ℎ to the previous commit
                                                          𝑙−
                                                           ℎ,𝑓

• File Growth: The change in number of lines on file 𝑓 from a commit ℎ to the previous commit

                                                𝛿ℎ,𝑓 ≔ 𝑙+      −
                                                        ℎ,𝑓 − 𝑙ℎ,𝑓

• File Churn: The number of changed lines on file 𝑓 from a commit ℎ to the previous commit

                                                𝜆ℎ,𝑓 ≔ 𝑙+      −
                                                        ℎ,𝑓 + 𝑙ℎ,𝑓




2.2 Directory Metrics
An immediate object is an object that is directly below the specified directory
foo/
  bar.txt        -- immediate child of foo
  baz/           -- immediate child of foo
     beef.py     -- immediate child of baz
     dead.py     -- immediate child of baz

A file 𝑓 is in a directory 𝑑 at a commit ℎ if it is in ℎ[𝐹 ] or ℎ[𝑝][𝐹 ] and is an immediate child of 𝑑.
Similarly for subdirectories 𝑑′ and ℎ[𝐷], ℎ[𝑝][𝐷].
• Directory Added Lines: The number of added lines across all immediate subdirectories 𝑑′ and files 𝑓
  in directory 𝑑
                                                      +        +
                                            𝑙+
                                             ℎ,𝑑 ≔ ∑ 𝑙ℎ,𝑓 + ∑ 𝑙ℎ,𝑑′
                                                    𝑓∈𝑑          𝑑′ ∈𝑑

• Directory Removed Lines: The number of removed lines across all immediate subdirectories 𝑑′ and
  files 𝑓 in directory 𝑑

                                            𝑙−        −        −
                                             ℎ,𝑑 ≔ ∑ 𝑙ℎ,𝑓 + ∑ 𝑙ℎ,𝑑′
                                                    𝑓∈𝑑          𝑑′ ∈𝑑

• Directory Growth: The net growth across all immediate subdirectories 𝑑′ and files 𝑓 in directory 𝑑




                                                      3/6
University of the Witwatersrand                   Metrics                                 COMS3011A Test




                                       𝛿ℎ,𝑑 ≔ ∑ 𝛿ℎ,𝑓 + ∑ 𝛿ℎ,𝑑′
                                                𝑓∈𝑑             𝑑′ ∈𝑑

• Directory Churn: The churn across all immediate subdirectories 𝑑′ and files 𝑓 in directory 𝑑

                                       𝜆ℎ,𝑑 ≔ ∑ 𝜆ℎ,𝑓 + ∑ 𝜆ℎ,𝑑′
                                                𝑓∈𝑑             𝑑′ ∈𝑑




2.3 Repository Metrics
Repository metrics are directory metrics on the root of the commit tree.


2.4 Commit set Metrics
• Added lines over a commit set 𝐻 in either a directory or file, 𝑜 ∈ 𝐻[𝐹 ] ∪ 𝐻[𝐷]
                                                         +
                                               𝑙+
                                                𝐻,𝑜 ≔ ∑ 𝑙ℎ,𝑜
                                                          ℎ∈𝐻

• Removed lines over a commit set 𝐻 in either a directory or file, 𝑜 ∈ 𝐻[𝐹 ] ∪ 𝐻[𝐷]

                                               𝑙−        −
                                                𝐻,𝑜 ≔ ∑ 𝑙ℎ,𝑜
                                                          ℎ∈𝐻

• Growth over a commit set 𝐻 in either a directory or file, 𝑜 ∈ 𝐻[𝐹 ] ∪ 𝐻[𝐷]

                                               𝛿𝐻,𝑜 ≔ ∑ 𝛿ℎ,𝑜
                                                          ℎ∈𝐻

• Churn over a commit set 𝐻 in either a directory or file, 𝑜 ∈ 𝐻[𝐹 ] ∪ 𝐻[𝐷]

                                               𝜆𝐻,𝑜 ≔ ∑ 𝜆ℎ,𝑜
                                                          ℎ∈𝐻

• Modifications: The number of commits that have at least some change on file or directory 𝑜 ∈ 𝐻[𝐹 ] ∪
  𝐻[𝐷]

                                                          1 if 𝜆ℎ,𝑜 > 0
                                        𝕀𝑛 (ℎ, 𝑜) ≔ {
                                                          0 otherwise

                                           𝑛𝐻,𝑜 ≔ ∑ 𝕀𝑛 (ℎ, 𝑜)
                                                      ℎ∈𝐻

• Modification frequency over a file or directory 𝑜 ∈ 𝐻[𝐹 ] ∪ 𝐻[𝐷]
                                                  𝑛𝐻,𝑜
                                                       if |𝐻| ≠ 0
                                        𝜂𝐻,𝑜   ≔ { |𝐻|
                                                      0     otherwise

• Churn rate over a file or directory 𝑜 ∈ 𝐻[𝐹 ] ∪ 𝐻[𝐷]
                                                  𝐻,𝑜 𝜆
                                                      if |𝐻| ≠ 0
                                        𝜌𝐻,𝑜 ≔ { |𝐻|
                                                0     otherwise




                                                      4/6
University of the Witwatersrand                         Rubric                                COMS3011A Test




2.5 Author Metrics
                                          1 if 𝑎=ℎ[𝑎]
We need an authorship test: 𝕀(𝑎, ℎ) ≔ {0 otherwise

• Author Modifications on a file or directory, 𝑜 ∈ 𝐻[𝐹 ] ∪ 𝐻[𝐷]

                                        𝑛𝐻,𝑜,𝑎 ≔ ∑ 𝕀(𝑎, ℎ) · 𝕀𝑛(ℎ,𝑜)
                                                    ℎ∈𝐻
• Author Churn on a file or directory, 𝑜 ∈ 𝐻[𝐹 ] ∪ 𝐻[𝐷]

                                         𝜆𝐻,𝑜,𝑎 ≔ ∑ 𝜆ℎ,𝑜 · 𝕀(𝑎, ℎ)
                                                        ℎ∈𝐻
• Author Ownership: The fraction of churn on file or directory, 𝑜 ∈ 𝐻[𝐹 ] ∪ 𝐻[𝐷] from an author 𝑎
                                                        𝜆𝐻,𝑜,𝑎
                                       𝜔𝐻,𝑜,𝑎 ≔          𝜆𝐻,𝑜 if 𝜆𝐻,𝑜 ≠ 0

                                                   {0            otherwise




3 Rubric
Requirements are cumulative. You can only reach a tier if the previous tier is satisfied. Each tier is
judged holistically.
Metric correctness is determined against a set of test repositories. Sample metrics from each of these
repos will be provided from a specific commit hash. These repos are open source.
Provided repositories:
• cJSON https://github.com/DaveGamble/cJSON.git
• Redis https://github.com/redis/redis.git
• Git https://github.com/git/git.git




                                                        5/6
University of the Witwatersrand                            Rubric                                     COMS3011A Test




 Criteria          Weight ≤ 25%                         ≤ 50%                ≤ 75%                ≤ 100%
 Requirements        50%          Implemented and       Implemented and      Implemented          Implemented all:
                                  correct for some      correct for all      either: Filtering,   Filtering, Author
                                  categories (repo,     metrics              Author Merge,        Merge, Multi-
                                  file, directory,      Both: zip file and   Multi-repo           repo support
                                  set, author) of       remote URL           support
                                  metrics               ingestion
                                  Either: zip file or
                                  remote URL
                                  ingestion
 Architectural       25%          Redundant &           Reasonable           Efficient            Efficient
 & UI Design                      slow metric           metric               algorithms for       algorithms and
                                  computation,          computation,         metric               architecture for
                                  poor                  okay                 computation,         metric
                                  visualisation of      visualisation of     good                 computation,
                                  metrics               metrics              visualisation of     inspired
                                                                             metrics              visualisation of
                                                                                                  metrics
 Usability           25%          Poor navigation,      Okay navigation,     Good navigation,     Excellent
                                  no error              minimal error        error handling,      navigation, good
                                  handling,             handling,            good                 performance on
                                  slow                  okay                 performance on       large (∼ 100000
                                  performance on        performance on       medium               commits) repos
                                  small (∼ 1000         small                repositories,
                                  commits)              repositories,        QoL features
                                  repositories,         slow
                                  no QoL features       performance on
                                                        medium (∼
                                                        10000 commits)
                                                        repos,
                                                        minimal to none
                                                        QoL features


AI Declaration: Claude Web (Opus 5.5) - reviewed




                                                            6/6
